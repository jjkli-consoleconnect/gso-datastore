"""
Cloud Function: Jira Changelogs Nightly Sync
Nightly backfill of Jira status transition changelogs routed via VPC; writes to BigQuery UAT.
"""
import logging
import uuid
import time
import random
import requests
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, secretmanager
import functions_framework

from jira_helpers import (
    load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table,
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists,
    execute_bq_query_with_retry
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

setup_root_logging()

JITTER_MAX_SECONDS = 0.3
MIN_PROGRESS_WINDOW_SEC = 600
MIN_WINDOW_HOURS = 1  # Skip windows smaller than 1 hour
OVERLAP_MINUTES = 10
MIN_START = datetime(2024, 7, 1, tzinfo=timezone.utc)
ENABLE_SOFT_DELETE_RECONCILIATION = os.environ.get('ENABLE_SOFT_DELETE_RECONCILIATION', '').strip().lower() == 'true'
BASE_WINDOW_DAYS = int(os.environ.get('BASE_WINDOW_DAYS', '1'))
BASE_WINDOW_HOURS = float(os.environ.get('BASE_WINDOW_HOURS', str(BASE_WINDOW_DAYS * 24)))
MIN_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MIN_ADAPTIVE_WINDOW_HOURS', '2'))
MAX_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MAX_ADAPTIVE_WINDOW_HOURS', '720'))
ADAPTIVE_TARGET_ROWS = int(os.environ.get('ADAPTIVE_TARGET_ROWS', '1500'))
ADAPTIVE_LOW_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_LOW_WATERMARK_ROWS', '300'))
ADAPTIVE_HIGH_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_HIGH_WATERMARK_ROWS', '5000'))

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
    'Vendor Verification Team',
    'IPECR',
    'Internal Knowledge Management',
    'ITOPS',
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
    """Ensure soft-delete and expanded changelog columns exist on the target table."""
    for ddl in [
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS IsDeleted BOOL",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS DeletedAt TIMESTAMP",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Changed_Field STRING",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Changed_FieldType STRING",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Change_Item_Index INT64",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS From_ID STRING",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS From_Value STRING",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS To_ID STRING",
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS To_Value STRING",
    ]:
        client.query(ddl).result()


def get_recent_window_metrics(client, dataset_id, table_id, project, sample_size=5):
    """Return recent complete windows for adaptive sizing."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('p', 'STRING', project),
            bigquery.ScalarQueryParameter('n', 'INT64', int(sample_size)),
        ]
    )
    rows = client.query(
        f"""
        SELECT
          RowCount,
          TIMESTAMP_DIFF(WindowEnd, WindowStart, SECOND) AS WindowSeconds
        FROM `{dataset_id}.{table_id}`
        WHERE Project=@p
          AND Status='complete'
          AND RowCount IS NOT NULL
          AND WindowEnd > WindowStart
        ORDER BY LastRun DESC
        LIMIT @n
        """,
        job_config=job_config,
    ).result()

    metrics = []
    for r in rows:
        try:
            rc = int(r.RowCount)
            sec = int(r.WindowSeconds)
            if sec > 0:
                metrics.append((rc, sec))
        except Exception:
            continue
    return metrics


def choose_window_hours(client, dataset_id, table_id, project):
    """Choose next window size using recent rows-per-hour density."""
    min_hours = max(MIN_ADAPTIVE_WINDOW_HOURS, 1.0)
    max_hours = max(MAX_ADAPTIVE_WINDOW_HOURS, min_hours)
    base_hours = min(max(BASE_WINDOW_HOURS, min_hours), max_hours)

    metrics = get_recent_window_metrics(client, dataset_id, table_id, project)
    if not metrics:
        logging.info(f"Adaptive window bootstrap (default): {base_hours:.2f}h")
        return base_hours

    total_rows = sum(rc for rc, _ in metrics)
    total_hours = sum(sec for _, sec in metrics) / 3600.0
    rows_per_hour = (total_rows / total_hours) if total_hours > 0 else 0.0
    last_rows = metrics[0][0]

    if rows_per_hour <= 0:
        adaptive_hours = max_hours
    else:
        adaptive_hours = ADAPTIVE_TARGET_ROWS / rows_per_hour

    if last_rows >= ADAPTIVE_HIGH_WATERMARK_ROWS:
        adaptive_hours *= 0.5
    elif last_rows <= ADAPTIVE_LOW_WATERMARK_ROWS:
        adaptive_hours *= 1.5

    adaptive_hours = min(max(adaptive_hours, min_hours), max_hours)
    logging.info(
        "Adaptive window chosen for %s: %.2fh (rows_per_hour=%.2f, last_rows=%s, sample=%s)",
        project,
        adaptive_hours,
        rows_per_hour,
        last_rows,
        len(metrics),
    )
    return adaptive_hours


def select_window(client, dataset_id, table_id, project):
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
            f"SELECT WindowEnd FROM `{dataset_id}.{table_id}` WHERE Project=@p ORDER BY WindowEnd DESC LIMIT 1",
            job_config=job_config,
        ).result()
        for r in res:
            latest = r.WindowEnd
            break
    except Exception:
        pass

    if latest:
        latest = to_utc_aware(latest)
        hours_from_latest = (now - latest).total_seconds() / 3600.0
        if hours_from_latest < MIN_WINDOW_HOURS:
            return None, None
        start = latest - timedelta(minutes=OVERLAP_MINUTES)
    else:
        start = MIN_START

    window_hours = choose_window_hours(client, dataset_id, table_id, project)
    end = start + timedelta(hours=window_hours)
    end = min(end, now)
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




def fetch_and_sync_jira_changelogs_nightly():
    config = load_config()
    if config is None:
        return

    jira_base_url = 'https://consoleconnect.atlassian.net'
    search_url = f"{jira_base_url}/rest/api/3/search/jql"
    username = config.get('jira_user') or config.get('jira_user_email') or 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')

    run_id = str(uuid.uuid4())
    table_id = 'JiraChangelog'
    temp_table_id = 'JiraChangelog_temp'
    temp_table_id_run = f"{temp_table_id}_{run_id[:8]}"
    progress_table_id = 'JiraChangelog_progress'
    dataset_id = 'GSO'
    pipeline_name = "GCP - JiraChangelogsNightly"
    client = None
    run_started = None
    total_rows = 0
    final_status = "ERROR"
    final_level = "ERROR"
    final_message = "Pipeline did not complete"
    final_error_code = None
    run_had_errors = False

    try:
        run_started = datetime.now(timezone.utc)
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

        ensure_soft_delete_columns(client, dataset_id, table_id)

        ensure_progress_table(client, dataset_id, progress_table_id)
        projects = DEFAULT_PROJECTS
        env_single = os.environ.get('SINGLE_PROJECT') or os.environ.get('PROJECT')
        env_projects = os.environ.get('PROJECTS')
        if env_single:
            projects = [env_single.strip()]
        elif env_projects:
            projects = [p.strip() for p in env_projects.split(',') if p.strip()]
        logging.info(f"Projects for changelogs nightly run: {projects}")

        bq_schema = [
            bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("History_ID", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Transition_Timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Changed_Field", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Changed_FieldType", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Change_Item_Index", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("From_ID", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("From_Value", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("To_ID", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("To_Value", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_From", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_To", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_By_Account_ID", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_By_Display_Name", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("IsDeleted", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("DeletedAt", "TIMESTAMP", mode="NULLABLE"),
        ]

        headers = {'Accept': 'application/json'}
        auth = (username, api_token)

        def fetch_issue_keys_paginated(jql):
            start_at = 0
            max_results = 100
            total = float('inf')
            keys = []
            had_error = False
            while start_at < total:
                try:
                    params = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': 'key'}
                    resp = requests.get(search_url, headers=headers, auth=auth, params=params, timeout=30)
                    if resp.status_code == 429:
                        ra = int(resp.headers.get('Retry-After', 30) or 30)
                        sleep_for = ra + random.uniform(0, JITTER_MAX_SECONDS)
                        logging.warning(f"429 search startAt={start_at}; sleeping {sleep_for:.1f}s")
                        time.sleep(sleep_for)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    issues = data.get('issues', [])
                    total = data.get('total', 0)
                    keys.extend([i.get('key') for i in issues if i.get('key')])
                    start_at += len(issues)
                    if not issues:
                        break
                except Exception as e:
                    logging.error(f"Issue search error: {e}")
                    had_error = True
                    break
            return keys, had_error

        def fetch_issue_history(issue_key):
            """Fetch changelog history for an issue with expand=changelog."""
            url = f"{jira_base_url}/rest/api/2/issue/{issue_key}"
            attempts = 0
            while attempts < 5:
                try:
                    params = {'expand': 'changelog'}
                    r = requests.get(url, headers=headers, auth=auth, params=params, timeout=30)
                    if r.status_code == 429:
                        ra = int(r.headers.get('Retry-After', 10) or 10)
                        sleep_for = ra + random.uniform(0, JITTER_MAX_SECONDS)
                        logging.warning(f"429 history {issue_key}; sleeping {sleep_for:.1f}s")
                        time.sleep(sleep_for)
                        continue
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    attempts += 1
                    if attempts >= 5:
                        logging.warning(f"Failed to fetch history for {issue_key}: {e}")
                        break
                    back = min(60, 2 ** attempts) + random.uniform(0, JITTER_MAX_SECONDS)
                    time.sleep(back)
            return None

        def generate_rows(issue_keys, ws_bound, we_bound):
            now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            # Ensure bounds are naive for comparison with parsed timestamps
            ws_naive = ws_bound.replace(tzinfo=None) if getattr(ws_bound, 'tzinfo', None) else ws_bound
            we_naive = we_bound.replace(tzinfo=None) if getattr(we_bound, 'tzinfo', None) else we_bound
            
            # Handle empty issue_keys
            if not issue_keys:
                return
            
            # Parallel fetching of issue histories
            max_workers = min(10, len(issue_keys))  # Cap at 10 parallel workers
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all fetch tasks
                future_to_key = {executor.submit(fetch_issue_history, key): key for key in issue_keys}
                
                # Process results as they complete
                for future in as_completed(future_to_key):
                    key = future_to_key[future]
                    try:
                        issue_data = future.result()
                    except Exception as e:
                        logging.warning(f"Failed to fetch history for {key}: {e}")
                        continue
                    
                    if not issue_data:
                        continue
                    
                    changelog = issue_data.get('changelog', {})
                    histories = changelog.get('histories', [])
                    for history in histories:
                        history_id = history.get('id')
                        created_str = history.get('created')
                        created_ts = convert_timestamp(created_str)
                        if not created_ts:
                            continue
                        try:
                            created_dt = datetime.strptime(created_ts, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            continue
                        if not (ws_naive <= created_dt < we_naive):
                            continue
                        author = history.get('author', {})
                        items = history.get('items', [])
                        for item_index, item in enumerate(items):
                            field = item.get('field')
                            yield {
                                "Issue_Key": key,
                                "History_ID": history_id,
                                "Transition_Timestamp": created_ts,
                                "Changed_Field": field,
                                "Changed_FieldType": item.get('fieldtype'),
                                "Change_Item_Index": item_index,
                                "From_ID": (None if item.get('from') is None else str(item.get('from'))),
                                "From_Value": item.get('fromString'),
                                "To_ID": (None if item.get('to') is None else str(item.get('to'))),
                                "To_Value": item.get('toString'),
                                "Transitioned_From": item.get('fromString') if field == 'status' else None,
                                "Transitioned_To": item.get('toString') if field == 'status' else None,
                                "Transitioned_By_Account_ID": author.get('accountId'),
                                "Transitioned_By_Display_Name": author.get('displayName'),
                                "SyncTime": now_str,
                                "IsDeleted": False,
                                "DeletedAt": None,
                            }

        # Clean up orphaned temp tables from previous crashed runs (older than 2h)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
            for tbl in client.list_tables(f"{client.project}.{dataset_id}"):
                if tbl.table_id.startswith(temp_table_id + '_') and tbl.table_id != temp_table_id_run:
                    tbl_ref = client.get_table(f"{dataset_id}.{tbl.table_id}")
                    if tbl_ref.created.replace(tzinfo=timezone.utc) < cutoff:
                        client.delete_table(tbl_ref, not_found_ok=True)
                        logging.info(f"Cleaned up orphaned temp table: {tbl.table_id}")
        except Exception as _cleanup_ex:
            logging.warning(f"Orphan temp table cleanup failed (non-fatal): {_cleanup_ex}")

        if not create_or_replace_temp_table(client, dataset_id, temp_table_id_run, bq_schema):
            logging.error("Setup failed: Could not create run-scoped temp table.")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message="Temp table create failed", status="ERROR")
            return
        if not wait_for_table(client, dataset_id, temp_table_id_run, retries=30, delay=2):
            logging.error("Setup failed: Temp table not available after create.")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message="Temp table wait failed", status="ERROR")
            return
        for proj in projects:
            logging.info(f"Starting nightly window selection for project {proj}")
            while True:
                ws, we = select_window(client, dataset_id, progress_table_id, proj)
                if not ws or not we:
                    logging.info(f"No further window for {proj} (too close to now or complete)")
                    break
                now = datetime.now(timezone.utc)
                if ws >= now:
                    logging.info(f"Window start >= now; stopping {proj}")
                    break
                mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'in_progress')
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Window in_progress", status="RUNNING", window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))

                proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
                time_clause = f"updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                jql_window = f"({proj_clause}) AND {time_clause}"
                logging.info(f"JQL (changelogs nightly window): {jql_window}")

                window_failed = False

                issue_keys, issue_keys_had_error = fetch_issue_keys_paginated(jql_window)
                logging.info(f"Issue keys fetched for changelogs: {len(issue_keys)}")

                if issue_keys_had_error:
                    run_had_errors = True
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=0)
                    break

                rows_to_insert = []
                rows_this_window = 0
                batch = 1000
                for row in generate_rows(issue_keys, ws, we):
                    rows_to_insert.append(row)
                    if len(rows_to_insert) >= batch:
                        if not insert_rows_resilient(client, dataset_id, temp_table_id_run, rows_to_insert, bq_schema):
                            mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                            run_had_errors = True
                            window_failed = True
                            break
                        rows_this_window += len(rows_to_insert)
                        total_rows += len(rows_to_insert)
                        rows_to_insert = []
                if window_failed:
                    break
                if rows_to_insert:
                    if not insert_rows_resilient(client, dataset_id, temp_table_id_run, rows_to_insert, bq_schema):
                        mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                        run_had_errors = True
                        window_failed = True
                    if window_failed:
                        break
                    rows_this_window += len(rows_to_insert)
                    total_rows += len(rows_to_insert)

                if window_failed:
                    break

                merge = f"""
                                    MERGE `{dataset_id}.{table_id}` T USING (SELECT DISTINCT * FROM `{dataset_id}.{temp_table_id_run}`) S
                  ON T.Issue_Key = S.Issue_Key
                    AND T.History_ID = S.History_ID
                    AND T.Transition_Timestamp = S.Transition_Timestamp
                    AND COALESCE(T.Changed_Field, 'status') = COALESCE(S.Changed_Field, 'status')
                    AND COALESCE(T.Change_Item_Index, 0) = COALESCE(S.Change_Item_Index, 0)
                                    WHEN MATCHED THEN UPDATE SET T.Changed_Field=S.Changed_Field,T.Changed_FieldType=S.Changed_FieldType,T.Change_Item_Index=S.Change_Item_Index,T.From_ID=S.From_ID,T.From_Value=S.From_Value,T.To_ID=S.To_ID,T.To_Value=S.To_Value,T.Transitioned_From=S.Transitioned_From,T.Transitioned_To=S.Transitioned_To,T.Transitioned_By_Account_ID=S.Transitioned_By_Account_ID,T.Transitioned_By_Display_Name=S.Transitioned_By_Display_Name,T.SyncTime=S.SyncTime,T.IsDeleted=FALSE,T.DeletedAt=NULL
                                    WHEN NOT MATCHED THEN INSERT (Issue_Key,History_ID,Transition_Timestamp,Changed_Field,Changed_FieldType,Change_Item_Index,From_ID,From_Value,To_ID,To_Value,Transitioned_From,Transitioned_To,Transitioned_By_Account_ID,Transitioned_By_Display_Name,SyncTime,IsDeleted,DeletedAt)
                                    VALUES (S.Issue_Key,S.History_ID,S.Transition_Timestamp,S.Changed_Field,S.Changed_FieldType,S.Change_Item_Index,S.From_ID,S.From_Value,S.To_ID,S.To_Value,S.Transitioned_From,S.Transitioned_To,S.Transitioned_By_Account_ID,S.Transitioned_By_Display_Name,S.SyncTime,FALSE,NULL)
                """
                try:
                    execute_bq_query_with_retry(client, merge, max_retries=5, initial_delay=10.0)
                    logging.info("Merged changelogs temp table into final table.")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'complete', row_count=rows_this_window)
                    try:
                        client.query(f"TRUNCATE TABLE `{dataset_id}.{temp_table_id_run}`").result()
                    except Exception as truncate_err:
                        logging.warning(f"Failed to truncate temp table after merge: {truncate_err}")
                except Exception as e:
                    logging.error(f"Merge failed: {e}")
                    run_had_errors = True
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=rows_this_window)

                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Window complete", status="SUCCESS", rows_merged=int(rows_this_window), duration_seconds=duration_seconds, window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))
                # Continue to next window if backlog remains

                if ENABLE_SOFT_DELETE_RECONCILIATION:
                        # Reconciliation step: soft-delete changelog rows for deleted/missing tickets; restore when ticket is active.
                        mark_deleted_query = f'''
                                UPDATE `{dataset_id}.{table_id}` C
                                SET IsDeleted = TRUE,
                                        DeletedAt = CURRENT_TIMESTAMP()
                                WHERE (C.IsDeleted IS NULL OR C.IsDeleted = FALSE)
                                    AND (
                                        NOT EXISTS (
                                            SELECT 1 FROM `{dataset_id}.JiraTickets` T
                                            WHERE T.Key = C.Issue_Key
                                        )
                                        OR EXISTS (
                                            SELECT 1 FROM `{dataset_id}.JiraTickets` T
                                            WHERE T.Key = C.Issue_Key AND COALESCE(T.IsDeleted, FALSE) = TRUE
                                        )
                                    )
                        '''
                        client.query(mark_deleted_query).result()

                        clear_deleted_query = f'''
                                UPDATE `{dataset_id}.{table_id}` C
                                SET IsDeleted = FALSE,
                                        DeletedAt = NULL
                                WHERE (C.IsDeleted IS TRUE OR C.DeletedAt IS NOT NULL)
                                    AND EXISTS (
                                        SELECT 1 FROM `{dataset_id}.JiraTickets` T
                                        WHERE T.Key = C.Issue_Key AND COALESCE(T.IsDeleted, FALSE) = FALSE
                                    )
                        '''
                        client.query(clear_deleted_query).result()
                else:
                        logging.warning("Soft-delete reconciliation disabled; skipping changelogs nightly delete-marking")

        if run_had_errors:
            final_status = "ERROR"
            final_level = "ERROR"
            final_message = "Pipeline finished with one or more errors"
        else:
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
                    rows_merged=int(total_rows),
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
            WHERE PipelineName = 'GCP - JiraChangelogsNightly'
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    try:
        fetch_and_sync_jira_changelogs_nightly()
        return {"status": "success", "message": "Jira changelogs nightly sync completed"}, 200
    except Exception as e:
        logging.error(f"Cloud Function failed: {e}")
        return {"status": "error", "message": str(e)}, 500
