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
MIN_START_ENV = os.environ.get('MIN_START', '2023-01-01T00:00:00Z')
MIN_START = datetime.fromisoformat(MIN_START_ENV.replace('Z', '+00:00'))
ENABLE_SOFT_DELETE_RECONCILIATION = os.environ.get('ENABLE_SOFT_DELETE_RECONCILIATION', '').strip().lower() == 'true'
MISSING_KEY_CATCHUP_PER_PROJECT = int(os.environ.get('MISSING_KEY_CATCHUP_PER_PROJECT', '50000'))
CACHE_BATCHED_FETCH_SIZE = int(os.environ.get('CACHE_BATCHED_FETCH_SIZE', '500'))  # Issues cached in each batch
CACHE_BATCH_DURATION_SEC = int(os.environ.get('CACHE_BATCH_DURATION_SEC', '120'))  # 2-minute window

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


def ensure_soft_delete_columns(client, dataset_id, table_id):
    """Ensure soft-delete columns exist on the target table."""
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS IsDeleted BOOL"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS DeletedAt TIMESTAMP"
    ).result()


def _to_sql_string_list(values):
    escaped = []
    for value in values:
        escaped.append("'" + str(value).replace("'", "''") + "'")
    return ", ".join(escaped)


def get_known_project_keys(client, dataset_id, table_id, project):
    """Return known non-empty keys already present in BQ for a project."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('p', 'STRING', project),
        ]
    )
    rows = client.query(
        f"""
        SELECT DISTINCT Key
        FROM `{dataset_id}.{table_id}`
        WHERE Project = @p
          AND Key IS NOT NULL
          AND TRIM(Key) <> ''
        """,
        job_config=job_config,
    ).result()
    return {r.Key for r in rows if getattr(r, 'Key', None)}


def get_very_stale_project_keys(client, dataset_id, table_id, project, stale_days=30):
    """Return keys in BQ that haven't been updated in > stale_days."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('p', 'STRING', project),
            bigquery.ScalarQueryParameter('stale_cutoff', 'TIMESTAMP', 
              (datetime.now(timezone.utc) - timedelta(days=stale_days))),
        ]
    )
    rows = client.query(
        f"""
        WITH latest AS (
          SELECT Key, SyncTime,
                 ROW_NUMBER() OVER (PARTITION BY Key ORDER BY SyncTime DESC, Updated DESC) AS rn
          FROM `{dataset_id}.{table_id}`
          WHERE Project = @p
            AND Key IS NOT NULL
            AND TRIM(Key) <> ''
        )
        SELECT DISTINCT Key
        FROM latest
        WHERE rn = 1 AND SyncTime < @stale_cutoff
        """,
        job_config=job_config,
    ).result()
    return {r.Key for r in rows if getattr(r, 'Key', None)}


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


def build_ticket_row(issue, sr_ref_jira_id, sr_ref_bq_name):
    if not issue:
        return None
    key = issue.get('key')
    if not key or not str(key).strip():
        return None
    fields = issue.get('fields', {})
    return {
        "T": fields.get('issuetype', {}).get('name'),
        "Project": fields.get('project', {}).get('name'),
        "Key": key,
        "Summary": fields.get('summary'),
        "Status": fields.get('status', {}).get('name'),
        "Created": convert_timestamp(fields.get('created')),
        "Updated": convert_timestamp(fields.get('updated')),
        "Resolved": convert_timestamp(fields.get('resolutiondate')),
        "Reporter": get_field_value(fields.get('reporter')),
        "Assignee": get_field_value(fields.get('assignee')),
        "Component": ', '.join([get_field_value(component) for component in fields.get('components', [])]) if fields.get('components') else None,
        "Links": extract_issue_links(fields.get('issuelinks')),
        sr_ref_bq_name: get_field_value(fields.get(sr_ref_jira_id)),
        "Priority": get_field_value(fields.get('priority')),
        "Resolution": get_field_value(fields.get('resolution')),
        "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
    }


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
    run_started = None
    total_rows_merged = 0
    final_status = "ERROR"
    final_level = "ERROR"
    final_message = "Pipeline did not complete"
    final_error_code = None

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

        ensure_soft_delete_columns(client, dataset_id, table_id)

        ticket_search_fields = [
            'key',
            'issuetype',
            'project',
            'summary',
            'status',
            'created',
            'updated',
            'resolutiondate',
            'reporter',
            'assignee',
            'components',
            'priority',
            'resolution',
            'issuelinks',
            SR_REF_JIRA_ID,
        ]

        def search_issues(jql: str, label: str, fields):
            headers_local = {'Accept': 'application/json'}
            start_at = 0
            max_results = 100
            all_issues = []
            auth_local = (username, api_token)
            had_error = False
            fields_param = ','.join(fields)

            while True:
                try:
                    params_local = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': fields_param}
                    resp = requests.get(jira_url, headers=headers_local, auth=auth_local, params=params_local, timeout=30)
                    if resp.status_code == 429:
                        ra = int(resp.headers.get('Retry-After', 30) or 30)
                        logging.warning(f"429 {label} search; sleeping {ra}s")
                        time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                        continue
                    resp.raise_for_status()
                    data_local = resp.json()
                    issues_local = data_local.get('issues', [])
                    total = data_local.get('total', 0)
                    all_issues.extend(issues_local)
                    start_at += len(issues_local)
                    if start_at >= total or not issues_local:
                        break
                except Exception as e:
                    had_error = True
                    logging.error(f"{label} pass error: {e}")
                    break

            logging.info(f"{label} pass fetched {len(all_issues)} issues")
            return all_issues, had_error

        def search_issue_keys(jql: str, label: str):
            issues, had_error = search_issues(jql, label, ['key'])
            keys = [issue.get('key') for issue in issues if issue.get('key')]
            logging.info(f"{label} pass fetched {len(keys)} issue keys")
            return keys, had_error

        def fetch_ticket_rows_for_keys(issue_keys, label):
            if not issue_keys:
                return []
            rows = []
            chunk_size = 50
            for index in range(0, len(issue_keys), chunk_size):
                key_chunk = issue_keys[index:index + chunk_size]
                keys_jql = ', '.join([f'"{key}"' for key in key_chunk if key])
                if not keys_jql:
                    continue
                chunk_jql = f"key in ({keys_jql})"
                issues, had_error = search_issues(chunk_jql, f"{label}:chunk{index // chunk_size + 1}", ticket_search_fields)
                if had_error:
                    logging.warning(f"{label} bulk fetch had Jira search errors for chunk {index // chunk_size + 1}")
                for issue in issues:
                    row = build_ticket_row(issue, SR_REF_JIRA_ID, SR_REF_BQ_NAME)
                    if row:
                        rows.append(row)
            return rows

        def fetch_and_insert_ticket_rows_batched(issue_keys, label, dataset_id_inner, temp_table_id_inner, bq_schema_inner):
            """
            Fetch and insert ticket rows in batches to minimize memory usage.
            Processes keys in CACHE_BATCHED_FETCH_SIZE chunks, fetching and inserting each batch.
            Returns total count inserted.
            """
            if not issue_keys:
                return 0
            
            total_inserted = 0
            batch_start_idx = 0
            
            while batch_start_idx < len(issue_keys):
                batch_end_idx = min(batch_start_idx + CACHE_BATCHED_FETCH_SIZE, len(issue_keys))
                batch_keys = issue_keys[batch_start_idx:batch_end_idx]
                
                logging.debug(f"{label}: Processing batch {batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1} "
                            f"({len(batch_keys)} keys, indices {batch_start_idx}-{batch_end_idx})")
                
                # Fetch rows for this batch
                batch_rows = []
                chunk_size = 50
                for chunk_idx in range(0, len(batch_keys), chunk_size):
                    key_chunk = batch_keys[chunk_idx:chunk_idx + chunk_size]
                    keys_jql = ', '.join([f'"{key}"' for key in key_chunk if key])
                    if not keys_jql:
                        continue
                    chunk_jql = f"key in ({keys_jql})"
                    issues, had_error = search_issues(chunk_jql, 
                                                    f"{label}:batch{batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}"
                                                    f":chunk{chunk_idx // chunk_size + 1}", 
                                                    ticket_search_fields)
                    if had_error:
                        logging.warning(f"{label} had Jira search errors for batch chunk")
                    for issue in issues:
                        row = build_ticket_row(issue, SR_REF_JIRA_ID, SR_REF_BQ_NAME)
                        if row:
                            batch_rows.append(row)
                
                # Insert this batch
                if batch_rows:
                    if insert_rows_resilient(client, dataset_id_inner, temp_table_id_inner, batch_rows, bq_schema_inner):
                        total_inserted += len(batch_rows)
                        logging.info(f"{label}: Inserted {len(batch_rows)} rows from batch "
                                   f"{batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}")
                    else:
                        logging.error(f"{label}: Failed to insert batch {batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}")
                        return total_inserted  # Return what we've inserted so far; let caller retry
                
                batch_start_idx = batch_end_idx
            
            return total_inserted

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
            project_current_keys = set()
            proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            
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

                time_clause = f"updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                resolved_clause = f"resolutiondate >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND resolutiondate < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                # Combined JQL - single search instead of two
                jql_combined = f"({proj_clause}) AND (({time_clause}) OR ({resolved_clause}))"
                logging.info(f"JQL combined window: {jql_combined}")

                rows_to_insert = []
                combined_issues, combined_had_error = search_issues(jql_combined, 'combined', ticket_search_fields)
                if combined_had_error:
                    logging.warning(f"Skipping window for project {proj} due to Jira search errors")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'degraded', row_count=0)
                    break
                seen_keys = set()
                for issue in combined_issues:
                    key = issue.get('key')
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    project_current_keys.add(key)
                    row = build_ticket_row(issue, SR_REF_JIRA_ID, SR_REF_BQ_NAME)
                    if row:
                        rows_to_insert.append(row)
                logging.info(f"Distinct issue keys to detail fetch: {len(seen_keys)}")

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
                            ) WHERE rownum = 1 AND Project = '{proj}' AND Key IS NOT NULL AND TRIM(Key) <> ''
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

            # Nightly catch-up: fill active Jira keys missing in BQ, and refresh very stale rows.
            if MISSING_KEY_CATCHUP_PER_PROJECT > 0:
                try:
                    catchup_keys, catchup_had_error = search_issue_keys(proj_clause, f'catchup_keyset:{proj}')
                    if catchup_had_error:
                        logging.warning(f"[{proj}] Catch-up skipped due to Jira key search errors")
                        continue
                    project_current_keys = {k for k in catchup_keys if k}
                    known_keys = get_known_project_keys(client, dataset_id, table_id, proj)
                    
                    # Find missing keys
                    missing_keys = sorted([k for k in project_current_keys if k not in known_keys])
                    
                    # Find very stale keys (>30 days old without update)
                    stale_keys = sorted(get_very_stale_project_keys(client, dataset_id, table_id, proj, stale_days=30))
                    
                    # Combine and deduplicate
                    to_refresh = sorted(set(missing_keys + stale_keys))
                    
                    # Limit total per run
                    to_fetch = to_refresh[:MISSING_KEY_CATCHUP_PER_PROJECT]
                    
                    if to_fetch:
                        missing_count = len([k for k in to_fetch if k in missing_keys])
                        stale_count = len([k for k in to_fetch if k in stale_keys])
                        logging.info(
                            f"[{proj}] Catch-up: {len(missing_keys)} missing keys, {len(stale_keys)} stale keys; "
                            f"fetching {len(to_fetch)} ({missing_count} missing + {stale_count} stale) this run"
                        )

                        # Use batched fetch and insert to minimize memory usage
                        catchup_rows_count = fetch_and_insert_ticket_rows_batched(
                            to_fetch, f'catchup:{proj}', dataset_id, temp_table_id_run, bq_schema
                        )

                        if catchup_rows_count > 0:
                            merge_query = f'''
                                MERGE `{dataset_id}.{table_id}` T
                                USING (
                                    SELECT * EXCEPT(rownum) FROM (
                                        SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum
                                        FROM `{dataset_id}.{temp_table_id_run}`
                                    ) WHERE rownum = 1 AND Project = '{proj}' AND Key IS NOT NULL AND TRIM(Key) <> ''
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
                            client.query(merge_query).result()
                            total_rows_merged += catchup_rows_count
                            logging.info(f"[{proj}] Catch-up merged {catchup_rows_count} missing key rows")
                except Exception as catchup_exc:
                    logging.warning(f"[{proj}] Missing-key catch-up skipped due to error: {catchup_exc}")

        if not ENABLE_SOFT_DELETE_RECONCILIATION:
            logging.warning("Soft-delete reconciliation disabled; skipping nightly delete-marking")
            final_status = "SUCCESS"
            final_level = "INFO"
            final_message = "Pipeline finished"
            return

        # Reconciliation step: mark rows as soft-deleted if key no longer exists in Jira.
        active_keys = set()
        failed_projects = []
        for proj in projects:
            proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            current_keys, had_error = search_issue_keys(proj_clause, f'full_keyset:{proj}')
            if had_error:
                failed_projects.append(proj)
                continue
            for key in current_keys:
                active_keys.add(key)

        if failed_projects:
            failed_projects_str = ', '.join(failed_projects)
            logging.error(f"Soft-delete reconciliation skipped due to Jira key fetch errors for projects: {failed_projects_str}")
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="WARNING",
                message=f"Soft-delete reconciliation skipped due to Jira key fetch errors for: {failed_projects_str}",
                status="SUCCESS",
            )
            final_status = "SUCCESS"
            final_level = "INFO"
            final_message = "Pipeline finished"
            return

        keys_table_id = f"JiraTickets_active_keys_{run_id.replace('-', '_')[:8]}"
        keys_schema = [bigquery.SchemaField("Key", "STRING", mode="REQUIRED")]
        if not create_or_replace_temp_table(client, dataset_id, keys_table_id, keys_schema):
            raise Exception("Failed to create active key snapshot table for soft-delete reconciliation")
        if not wait_for_table(client, dataset_id, keys_table_id, retries=30, delay=2):
            raise Exception("Active key snapshot table was not available for reconciliation")

        keys_rows = [{"Key": k} for k in active_keys]
        if keys_rows:
            if not insert_rows_resilient(client, dataset_id, keys_table_id, keys_rows, keys_schema):
                raise Exception("Failed to populate active key snapshot table")

        scoped_projects = _to_sql_string_list(projects)
        mark_deleted_query = f'''
            UPDATE `{dataset_id}.{table_id}` T
            SET IsDeleted = TRUE,
                DeletedAt = CURRENT_TIMESTAMP()
            WHERE T.Project IN ({scoped_projects})
                            AND T.Key IS NOT NULL
                            AND TRIM(T.Key) <> ''
              AND (T.IsDeleted IS NULL OR T.IsDeleted = FALSE)
              AND NOT EXISTS (
                SELECT 1
                FROM `{dataset_id}.{keys_table_id}` S
                WHERE S.Key = T.Key
              )
        '''
        client.query(mark_deleted_query).result()

        clear_deleted_query = f'''
            UPDATE `{dataset_id}.{table_id}` T
            SET IsDeleted = FALSE,
                DeletedAt = NULL
            WHERE T.Project IN ({scoped_projects})
                            AND T.Key IS NOT NULL
                            AND TRIM(T.Key) <> ''
              AND EXISTS (
                SELECT 1
                FROM `{dataset_id}.{keys_table_id}` S
                WHERE S.Key = T.Key
              )
              AND (T.IsDeleted IS TRUE OR T.DeletedAt IS NOT NULL)
        '''
        client.query(clear_deleted_query).result()

        delete_temp_table(client, dataset_id, keys_table_id)

        final_status = "SUCCESS"
        final_level = "INFO"
        final_message = "Pipeline finished"
    except Exception as e:
        final_status = "ERROR"
        final_level = "ERROR"
        final_message = f"Exception: {e}"
        final_error_code = getattr(e, "code", None)
        raise
    finally:
        try:
            if client and run_started:
                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level=final_level,
                    message=final_message,
                    status=final_status,
                    rows_merged=total_rows_merged,
                    error_code=final_error_code,
                    duration_seconds=duration_seconds,
                )
        except Exception as log_err:
            logging.warning(f"Failed to write final pipeline status for {run_id}: {log_err}")

        try:
            if client:
                delete_temp_table(client, dataset_id, temp_table_id_run)
        except Exception as cleanup_err:
            logging.warning(f"Failed to cleanup temp table {temp_table_id_run}: {cleanup_err}")

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
