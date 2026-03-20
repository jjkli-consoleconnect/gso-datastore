"""
One-off historical rebaseline for JiraTickets.

Fetches all active keys from Jira for each project and updates BigQuery
with current ticket details, regardless of how old the existing BQ rows are.

Usage:
  python refresh_jira_tickets_historical.py [--dry-run] [--project PROJECT_NAME]

Examples:
  python refresh_jira_tickets_historical.py --dry-run
    (Shows what would be updated without modifying BQ)

  python refresh_jira_tickets_historical.py --project "Global Service Delivery Team"
    (Rebaseline only GSDT)

  python refresh_jira_tickets_historical.py
    (Rebaseline all projects)
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import requests
from google.cloud import bigquery, secretmanager

# Import shared helpers from CloudFunctions/JiraTicketsNightly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'CloudFunctions', 'JiraTicketsNightly'))
from jira_helpers import convert_timestamp, create_or_replace_temp_table, delete_temp_table

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'pccw-internal-virt-agent-uat'
DATASET_ID = 'GSO'
TABLE_ID = 'JiraTickets'

DEFAULT_PROJECTS = [
    'GS&O Data Analytics',
    'Customer Success Management',
    'GS&O Tool Automation',
    'GS&O Knowledge Consolidation',
    'TAC',
    'VOICE - CE',
    'IOT CE',
    'Console Application Support',
    'Console Connect Provisioning',
    'Global Service Delivery Team',
    'Transmission TX-CE',
    'Mobility SMS - CE',
    'Managed Security Services',
    'Sherbet',
    'Google Contact Center AI Solution',
    'QMS Documentation',
    'Operational Case Reviews',
    'IT Helpdesk',
    'GS&O Strategic Initiatives',
]

SR_REF_JIRA_ID = 'customfield_10045'
SR_REF_BQ_NAME = 'SR_Reference'


def get_field_value(field):
    """Extract display-friendly value from Jira field object."""
    if field is None:
        return None
    elif isinstance(field, dict):
        return field.get('value') or field.get('name') or field.get('displayName')
    elif isinstance(field, list):
        return ', '.join([str(item.get('value') or item.get('name') or item.get('displayName') if isinstance(item, dict) else item) for item in field])
    elif isinstance(field, bool):
        return str(field)
    else:
        return str(field)


def load_config():
    """Load Jira credentials from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    
    email_name = f'projects/{PROJECT_ID}/secrets/jira-email/versions/latest'
    token_name = f'projects/{PROJECT_ID}/secrets/jira-api-token/versions/latest'
    
    email_response = client.access_secret_version(request={'name': email_name})
    email = email_response.payload.data.decode('UTF-8').strip()
    
    token_response = client.access_secret_version(request={'name': token_name})
    token = token_response.payload.data.decode('UTF-8').strip()
    
    return email, token


def extract_issue_links(issuelinks):
    """Extract and format issue links."""
    if not issuelinks:
        return None
    links = []
    for link in issuelinks:
        key = link.get('outwardIssue', {}).get('key') or link.get('inwardIssue', {}).get('key')
        if key:
            links.append(key)
    return ', '.join(links) if links else None


def build_ticket_row(issue):
    """Build a ticket row from Jira issue payload."""
    if not issue:
        return None
    key = issue.get('key')
    if not key or not str(key).strip():
        return None
    fields = issue.get('fields', {})
    return {
        'T': fields.get('issuetype', {}).get('name'),
        'Project': fields.get('project', {}).get('name'),
        'Key': key,
        'Summary': fields.get('summary'),
        'Status': fields.get('status', {}).get('name'),
        'Created': convert_timestamp(fields.get('created')),
        'Updated': convert_timestamp(fields.get('updated')),
        'Resolved': convert_timestamp(fields.get('resolutiondate')),
        'Reporter': get_field_value(fields.get('reporter')),
        'Assignee': get_field_value(fields.get('assignee')),
        'Component': ', '.join([get_field_value(c) for c in fields.get('components', [])]) if fields.get('components') else None,
        'Links': extract_issue_links(fields.get('issuelinks')),
        SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
        'Priority': get_field_value(fields.get('priority')),
        'Resolution': get_field_value(fields.get('resolution')),
        'SyncTime': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
    }


def search_issues_bulk(jql: str, label: str, fields: List[str], username: str, api_token: str) -> tuple:
    """Paginate through Jira search results and return all issues."""
    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    headers = {'Accept': 'application/json'}
    auth = (username, api_token)
    
    start_at = 0
    max_results = 100
    all_issues = []
    had_error = False
    fields_param = ','.join(fields)
    
    while True:
        try:
            params = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': fields_param}
            resp = requests.get(jira_url, headers=headers, auth=auth, params=params, timeout=30)
            
            if resp.status_code == 429:
                ra = int(resp.headers.get('Retry-After', 30) or 30)
                logger.warning(f'Rate limited on {label}; sleeping {ra}s')
                import time
                time.sleep(ra)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            issues = data.get('issues', [])
            total = data.get('total', 0)
            
            all_issues.extend(issues)
            start_at += len(issues)
            
            if start_at >= total or not issues:
                break
        except Exception as e:
            had_error = True
            logger.error(f'{label} search error: {e}')
            break
    
    logger.info(f'{label}: fetched {len(all_issues)} issues')
    return all_issues, had_error


def rebaseline_project(client: bigquery.Client, project: str, username: str, api_token: str, dry_run: bool = False):
    """Rebaseline all tickets for a single project."""
    logger.info(f'Starting rebaseline for project: {project}')
    
    # Search for all active keys in project
    proj_clause = f'project = "{project}"' if (' ' in project or '&' in project) else f'project = {project}'
    jql = f'{proj_clause} ORDER BY key'
    
    ticket_search_fields = [
        'key', 'issuetype', 'project', 'summary', 'status', 'created', 'updated',
        'resolutiondate', 'reporter', 'assignee', 'components', 'priority',
        'resolution', 'issuelinks', SR_REF_JIRA_ID,
    ]
    
    issues, had_error = search_issues_bulk(jql, f'rebaseline:{project}', ticket_search_fields, username, api_token)
    
    if had_error:
        logger.warning(f'[{project}] Search had errors, but continuing with retrieved issues')
    
    if not issues:
        logger.warning(f'[{project}] No issues found')
        return 0
    
    # Build rows
    rows = []
    for issue in issues:
        row = build_ticket_row(issue)
        if row:
            rows.append(row)
    
    logger.info(f'[{project}] Built {len(rows)} ticket rows')
    
    if dry_run:
        logger.info(f'[{project}] DRY RUN: Would upsert {len(rows)} rows')
        return len(rows)
    
    # Create temp table
    bq_schema = [
        bigquery.SchemaField('T', 'STRING'),
        bigquery.SchemaField('Project', 'STRING'),
        bigquery.SchemaField('Key', 'STRING'),
        bigquery.SchemaField('Summary', 'STRING'),
        bigquery.SchemaField('Status', 'STRING'),
        bigquery.SchemaField('Created', 'TIMESTAMP'),
        bigquery.SchemaField('Updated', 'TIMESTAMP'),
        bigquery.SchemaField('Resolved', 'TIMESTAMP'),
        bigquery.SchemaField('Reporter', 'STRING'),
        bigquery.SchemaField('Assignee', 'STRING'),
        bigquery.SchemaField('Component', 'STRING'),
        bigquery.SchemaField('Links', 'STRING'),
        bigquery.SchemaField(SR_REF_BQ_NAME, 'STRING'),
        bigquery.SchemaField('Priority', 'STRING'),
        bigquery.SchemaField('Resolution', 'STRING'),
        bigquery.SchemaField('SyncTime', 'TIMESTAMP'),
    ]
    
    import uuid
    temp_table_id = f'{TABLE_ID}_rebaseline_{uuid.uuid4().hex[:8]}'
    
    try:
        if not create_or_replace_temp_table(client, DATASET_ID, temp_table_id, bq_schema):
            logger.error(f'[{project}] Failed to create temp table')
            return 0
        
        # Insert rows
        errors = client.insert_rows_json(f'{DATASET_ID}.{temp_table_id}', rows)
        if errors:
            logger.error(f'[{project}] Insert errors: {errors}')
            return 0
        
        logger.info(f'[{project}] Inserted {len(rows)} rows into temp table')
        
        # Merge into main table
        merge_query = f'''
            MERGE `{DATASET_ID}.{TABLE_ID}` T
            USING (
                SELECT * EXCEPT(rownum) FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum
                    FROM `{DATASET_ID}.{temp_table_id}`
                ) WHERE rownum = 1
            ) S
            ON T.Key = S.Key
            WHEN MATCHED THEN UPDATE SET
                T.T = S.T,
                T.Project = S.Project,
                T.Summary = S.Summary,
                T.Status = S.Status,
                T.Priority = S.Priority,
                T.Resolution = S.Resolution,
                T.Created = S.Created,
                T.Updated = S.Updated,
                T.Resolved = S.Resolved,
                T.Reporter = S.Reporter,
                T.Assignee = S.Assignee,
                T.Component = IF(S.Component IS NULL, NULL, [S.Component]),
                T.{SR_REF_BQ_NAME} = S.{SR_REF_BQ_NAME},
                T.SyncTime = S.SyncTime,
                T.IsDeleted = FALSE,
                T.DeletedAt = NULL
            WHEN NOT MATCHED THEN INSERT (T, Project, Key, Summary, Status, Priority, Resolution, Created, Updated, Resolved, Reporter, Assignee, Component, {SR_REF_BQ_NAME}, SyncTime, IsDeleted, DeletedAt)
            VALUES (S.T, S.Project, S.Key, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, IF(S.Component IS NULL, NULL, [S.Component]), S.{SR_REF_BQ_NAME}, S.SyncTime, FALSE, NULL)
        '''
        
        job = client.query(merge_query)
        job.result()
        logger.info(f'[{project}] Merge completed successfully')
        
        return len(rows)
    
    finally:
        try:
            delete_temp_table(client, DATASET_ID, temp_table_id)
        except Exception as e:
            logger.warning(f'Failed to delete temp table {temp_table_id}: {e}')


def main():
    parser = argparse.ArgumentParser(description='Rebaseline historical JiraTickets data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without modifying')
    parser.add_argument('--project', type=str, help='Rebaseline only this project (e.g., "Global Service Delivery Team")')
    args = parser.parse_args()
    
    logger.info('Loading Jira credentials...')
    username, api_token = load_config()
    
    client = bigquery.Client(project=PROJECT_ID)
    
    projects_to_rebaseline = [args.project] if args.project else DEFAULT_PROJECTS
    
    if args.dry_run:
        logger.info('DRY RUN MODE: No changes will be made to BigQuery')
    
    total_rows = 0
    for project in projects_to_rebaseline:
        try:
            rows = rebaseline_project(client, project, username, api_token, dry_run=args.dry_run)
            total_rows += rows
        except Exception as e:
            logger.error(f'Failed to rebaseline {project}: {e}', exc_info=True)
    
    logger.info(f'Rebaseline complete. Total rows processed: {total_rows}')


if __name__ == '__main__':
    main()
