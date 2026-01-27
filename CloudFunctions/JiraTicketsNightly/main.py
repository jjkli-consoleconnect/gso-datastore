"""
Cloud Function: Jira Tickets Nightly Sync
Nightly backfill of Jira ticket data routed via VPC; writes to BigQuery UAT.
"""
import requests
import logging
import uuid
import time
import random
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, secretmanager
import functions_framework

# Import shared helper functions (files in same directory)
from jira_helpers import (
    load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table,
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

setup_root_logging()

JITTER_MAX_SECONDS = 0.3
MIN_PROGRESS_WINDOW_SEC = 600  # 10 minutes to avoid thrashing tiny windows
MIN_WINDOW_HOURS = 1  # Skip windows smaller than 1 hour
OVERLAP_MINUTES = 10
MIN_START = datetime(2024, 7, 1, tzinfo=timezone.utc)

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
    'GS&O Strategic Initiatives'
]


def to_utc_aware(dt):
    if dt is None:
        return None
    if getattr(dt, 'tzinfo', None):
        try:
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def ensure_progress_table(client, dataset_id, table_id):
    schema = (
        "WindowStart TIMESTAMP, WindowEnd TIMESTAMP, Status STRING, "
        "LastRun TIMESTAMP, Project STRING, RowCount INT64"
    )
    client.query(
        f"CREATE TABLE IF NOT EXISTS `{dataset_id}.{table_id}` ({schema})"
    ).result()


def select_window(client, dataset_id, table_id, project, base_days=3):
    now = datetime.now(timezone.utc)
    ws = None
    we = None
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('p', 'STRING', project)]
    )
    try:
        res = client.query(
            f"SELECT WindowStart, WindowEnd FROM `{dataset_id}.{table_id}` "
            "WHERE Project=@p AND Status NOT IN ('complete','degraded') "
            "ORDER BY WindowStart ASC LIMIT 1",
            job_config=job_config,
        ).result()
        for r in res:
            ws = r.WindowStart
            we = r.WindowEnd
            break
    except Exception:
        pass

    if ws and we:
        return to_utc_aware(ws), to_utc_aware(we)

    latest = None
    try:
        res = client.query(
            f"SELECT WindowEnd FROM `{dataset_id}.{table_id}` "
            "WHERE Project=@p ORDER BY WindowEnd DESC LIMIT 1",
            job_config=job_config,
        ).result()
        for r in res:
            latest = r.WindowEnd
            break
    except Exception:
        pass

    if latest:
        latest = to_utc_aware(latest)
        # Check if we're too close to now to create a meaningful window
        hours_from_latest = (now - latest).total_seconds() / 3600.0
        if hours_from_latest < MIN_WINDOW_HOURS:
            # Return None to signal no window available
            return None, None
        start = latest - timedelta(minutes=OVERLAP_MINUTES)
    else:
        start = MIN_START

    end = start + timedelta(days=base_days)
    end = min(end, now)

    # Final check: if resulting window is too small, return None
    try:
        if (end - start).total_seconds() / 3600.0 < MIN_WINDOW_HOURS:
            return None, None
    except Exception:
        pass

    return start, end


def mark_progress(client, dataset_id, table_id, project, ws, we, status, row_count=None):
    rc_val = 'NULL' if row_count is None else row_count
    ws_str = to_utc_aware(ws).strftime('%Y-%m-%d %H:%M:%S') if ws else None
    we_str = to_utc_aware(we).strftime('%Y-%m-%d %H:%M:%S') if we else None
    client.query(
        f"""
        MERGE `{dataset_id}.{table_id}` T
        USING (SELECT TIMESTAMP('{ws_str}') AS WindowStart, TIMESTAMP('{we_str}') AS WindowEnd, '{project}' AS Project) S
        ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project
        WHEN MATCHED THEN UPDATE SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc_val}, Project=S.Project
        WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project,RowCount)
        VALUES (S.WindowStart,S.WindowEnd,'{status}',CURRENT_TIMESTAMP(),S.Project,{rc_val})
        """
    ).result()


def get_secret(secret_id, project_id="pccw-internal-virtual-agent"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')


def insert_rows_resilient(client, dataset_id, temp_table_id, rows, bq_schema, max_attempts=3):
    """Insert rows with resilience: retry, and recreate temp table if needed."""
    if not rows:
        return True
    
    for attempt in range(max_attempts):
        # First, try to insert using the standard retry logic
        if insert_rows_with_retry(client, dataset_id, temp_table_id, rows, bq_schema, retries=5, delay=3):
            return True
        
        # If insert failed, check if table still exists; if not, recreate and retry
        if not table_exists(client, dataset_id, temp_table_id):
            logging.warning(f"Temp table missing after failed insert attempt {attempt + 1}/{max_attempts}. Recreating...")
            if create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
                if wait_for_table(client, dataset_id, temp_table_id, retries=15, delay=1):
                    # Retry insert after recreation
                    if insert_rows_with_retry(client, dataset_id, temp_table_id, rows, bq_schema, retries=5, delay=3):
                        return True
        
        if attempt < max_attempts - 1:
            time.sleep(2 * (1.5 ** attempt))
    
    logging.error(f"Failed to insert rows after {max_attempts} resilient attempts")
    return False


def load_config():
    try:
        api_token = get_secret("jira-api-token")
        user_email = get_secret("jira-user-email")
        return {"jira_api_token": api_token, "jira_user": user_email}
    except Exception as e:
        logging.error(f"Failed to load config from Secret Manager: {e}")
        return None


def get_field_value(field):
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


def extract_issue_links(issuelinks):
    if not issuelinks or not isinstance(issuelinks, list):
        return None
    links = []
    def get_status(issue):
        if not issue:
            return None
        fields = issue.get('fields', {})
        status = fields.get('status', {})
        return status.get('name')
    for link in issuelinks:
        outward = link.get('outwardIssue')
        inward = link.get('inwardIssue')
        if outward:
            key = outward.get('key')
            status = get_status(outward)
            if key:
                if status:
                    links.append(f"{link.get('type', {}).get('outward', 'links to')}: {key} [{status}]")
                else:
                    links.append(f"{link.get('type', {}).get('outward', 'links to')}: {key}")
        if inward:
            key = inward.get('key')
            status = get_status(inward)
            if key:
                if status:
                    links.append(f"{link.get('type', {}).get('inward', 'links to')}: {key} [{status}]")
                else:
                    links.append(f"{link.get('type', {}).get('inward', 'links to')}: {key}")
    return ', '.join(links) if links else None


def fetch_and_sync_jira_tickets_nightly():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    username = config.get('jira_user')
    api_token = config.get('jira_api_token')

    SR_REF_JIRA_ID = 'customfield_10382'
    SR_REF_BQ_NAME = 'SR_Ref'

    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    progress_table_id = 'JiraTickets_progress'
    pipeline_name = "GCP - JiraTicketsNightly"

    run_id = str(uuid.uuid4())
    client = None

    try:
        run_started = datetime.now(timezone.utc)

        # Write to UAT BigQuery
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        dataset_id = 'GSO'

        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

        ensure_progress_table(client, dataset_id, progress_table_id)
        projects = DEFAULT_PROJECTS
        env_single = os.environ.get('SINGLE_PROJECT') or os.environ.get('PROJECT')
        env_projects = os.environ.get('PROJECTS')
        if env_single:
            projects = [env_single.strip()]
        elif env_projects:
            projects = [p.strip() for p in env_projects.split(',') if p.strip()]
        logging.info(f"Projects for nightly run: {projects}")

        # Schema aligned with hourly tickets
        bq_schema = [
            bigquery.SchemaField("T", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Project", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Priority", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Resolution", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Component", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SR_REF_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
        ]

        def fetch_issue_detail(issue_key):
            issue_url = f"https://consoleconnect.atlassian.net/rest/api/3/issue/{issue_key}"
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            auth = (username, api_token)
            try:
                issue_resp = requests.get(issue_url, headers=headers, auth=auth, timeout=30)
                issue_resp.raise_for_status()
                full_issue = issue_resp.json()
                fields = full_issue.get('fields', {})
                row = {
                    "T": fields.get('issuetype', {}).get('name'),
                    "Project": fields.get('project', {}).get('name'),
                    "Key": issue_key,
                    "Summary": fields.get('summary'),
                    "Status": fields.get('status', {}).get('name'),
                    "Created": convert_timestamp(fields.get('created')),
                    "Updated": convert_timestamp(fields.get('updated')),
                    "Resolved": convert_timestamp(fields.get('resolutiondate')),
                    "Reporter": get_field_value(fields.get('reporter')),
                    "Assignee": get_field_value(fields.get('assignee')),
                    "Component": ', '.join([get_field_value(c) for c in fields.get('components', [])]) if fields.get('components') else None,
                    "Links": None,
                    SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
                    "Priority": get_field_value(fields.get('priority')),
                    "Resolution": get_field_value(fields.get('resolution')),
                    "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                }
                return row
            except Exception as e:
                logging.warning(f"Could not fetch full details for issue {issue_key}: {e}")
                return None

        total_rows_merged = 0
        # Use single temp table with run_id suffix for all projects
        temp_table_id_run = f"{temp_table_id}_{run_id.replace('-', '_')[:8]}"
        
        # Create temp table once for all projects
        if not create_or_replace_temp_table(client, dataset_id, temp_table_id_run, bq_schema):
            logging.error("Failed to create temp table for run.")
            raise Exception("Could not create temp table")
        if not wait_for_table(client, dataset_id, temp_table_id_run, retries=30, delay=2):
            logging.error("Temp table not available after extended wait.")
            raise Exception("Temp table not available")
        
        for proj in projects:
            logging.info(f"Starting nightly window selection for project {proj}")
            
            while True:
                ws, we = select_window(client, dataset_id, progress_table_id, proj, base_days=1)
                if not ws or not we:
                    logging.info(f"No further window for {proj} (too close to now or complete)")
                    break
                now = datetime.now(timezone.utc)
                if ws >= now:
                    logging.info(f"Window start >= now; stopping {proj}")
                    break
                mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'in_progress')
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="INFO",
                    message="Window in_progress",
                    status="RUNNING",
                    window_start=ws.strftime('%Y-%m-%d %H:%M:%S'),
                    window_end=we.strftime('%Y-%m-%d %H:%M:%S'),
                )

                proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
                time_clause = f"updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                resolved_clause = f"resolutiondate >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND resolutiondate < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                jql_updated = f"({proj_clause}) AND {time_clause}"
                jql_resolved = f"({proj_clause}) AND {resolved_clause}"
                logging.info(f"JQL updated window: {jql_updated}")
                logging.info(f"JQL resolved window: {jql_resolved}")

                rows_to_insert = []
                issue_keys_total = set()

                def search_issue_keys(jql: str, label: str):
                    headers_local = {'Accept': 'application/json'}
                    params_local = {'jql': jql, 'startAt': 0, 'maxResults': 100, 'fields': 'key'}
                    auth_local = (username, api_token)
                    try:
                        resp = requests.get(jira_url, headers=headers_local, auth=auth_local, params=params_local, timeout=30)
                        if resp.status_code == 429:
                            ra = int(resp.headers.get('Retry-After', 30) or 30)
                            logging.warning(f"429 {label} search; sleeping {ra}s")
                            time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                            return []
                        resp.raise_for_status()
                        data_local = resp.json()
                        issues_local = data_local.get('issues', [])
                        keys = [i.get('key') for i in issues_local if i.get('key')]
                        logging.info(f"{label} pass fetched {len(keys)} issue keys")
                        return keys
                    except Exception as e:
                        logging.error(f"{label} pass error: {e}")
                        return []

                updated_keys = search_issue_keys(jql_updated, 'updated')
                for k in updated_keys:
                    issue_keys_total.add(k)
                resolved_keys = search_issue_keys(jql_resolved, 'resolved')
                new_resolved = [k for k in resolved_keys if k not in issue_keys_total]
                for k in new_resolved:
                    issue_keys_total.add(k)
                logging.info(f"Distinct issue keys to detail fetch (union): {len(issue_keys_total)}")

                BULK_FETCH_SIZE = 50
                for i in range(0, len(issue_keys_total), BULK_FETCH_SIZE):
                    batch_keys = list(issue_keys_total)[i:i + BULK_FETCH_SIZE]
                    with ThreadPoolExecutor(max_workers=min(10, len(batch_keys))) as executor:
                        fut_map = {executor.submit(fetch_issue_detail, key): key for key in batch_keys}
                        for fut in as_completed(fut_map):
                            row = fut.result()
                            if row:
                                rows_to_insert.append(row)
                    logging.info(f"Detail fetched batch {i // BULK_FETCH_SIZE + 1}; cumulative rows={len(rows_to_insert)}")

                if rows_to_insert:
                    if not insert_rows_resilient(client, dataset_id, temp_table_id_run, rows_to_insert, bq_schema):
                        logging.error("Failed to insert rows into temp table after retries.")
                        mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                        break

                try:
                    merge_query = f'''
                        MERGE `{dataset_id}.{table_id}` T
                        USING (
                            SELECT * EXCEPT(rownum) FROM (
                                SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum FROM `{dataset_id}.{temp_table_id_run}`
                            ) WHERE rownum = 1 AND Project = '{proj}'
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
                            T.SyncTime = S.SyncTime
                        WHEN NOT MATCHED THEN INSERT (T, Project, Key, Summary, Status, Priority, Resolution, Created, Updated, Resolved, Reporter, Assignee, Component, {SR_REF_BQ_NAME}, SyncTime)
                        VALUES (S.T, S.Project, S.Key, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, IF(S.Component IS NULL, NULL, [S.Component]), S.{SR_REF_BQ_NAME}, S.SyncTime)
                    '''
                    client.query(merge_query).result()
                    logging.info(f"Merged temp table into '{dataset_id}.{table_id}'.")
                except Exception as e:
                    logging.error(f"Error merging temp table: {e}")

                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                total_rows_merged += len(rows_to_insert)
                mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'complete', row_count=len(rows_to_insert))
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="INFO",
                    message="Window complete",
                    status="SUCCESS",
                    rows_merged=len(rows_to_insert),
                    duration_seconds=duration_seconds,
                    window_start=ws.strftime('%Y-%m-%d %H:%M:%S'),
                    window_end=we.strftime('%Y-%m-%d %H:%M:%S'),
                )
                # Move to next window for this project

        # Clean up temp table after all projects processed
        delete_temp_table(client, dataset_id, temp_table_id_run)
        
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline finished",
            status="SUCCESS",
            rows_merged=total_rows_merged,
            duration_seconds=duration_seconds,
        )
    except Exception as e:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="ERROR",
            message=f"Exception: {e}",
            status="ERROR",
            error_code=getattr(e, "code", None),
            duration_seconds=duration_seconds,
        )
        raise


@functions_framework.http
def main(request):
    # Cleanup stale RUNNING entries older than 2 hours
    try:
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        cleanup_query = '''
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = 'GCP - JiraTicketsNightly'
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    try:
        fetch_and_sync_jira_tickets_nightly()
        return {"status": "success", "message": "Jira tickets nightly sync completed"}, 200
    except Exception as e:
        logging.error(f"Cloud Function failed: {e}")
        return {"status": "error", "message": str(e)}, 500
