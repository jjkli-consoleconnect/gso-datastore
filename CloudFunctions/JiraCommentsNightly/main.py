"""
Cloud Function: Jira Comments Nightly Sync
Nightly backfill of Jira comments routed via VPC; writes to BigQuery UAT.
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
DEFAULT_BASE_WINDOW_DAYS = int(os.environ.get('BASE_WINDOW_DAYS', '1'))
BACKFILL_MODE = os.environ.get('BACKFILL_MODE', '').strip().lower() == 'true'
BACKFILL_BASE_WINDOW_DAYS = int(os.environ.get('BACKFILL_BASE_WINDOW_DAYS', '14'))
MAX_BASE_WINDOW_DAYS = int(os.environ.get('MAX_BASE_WINDOW_DAYS', '30'))
BASE_WINDOW_HOURS = float(os.environ.get('BASE_WINDOW_HOURS', str(DEFAULT_BASE_WINDOW_DAYS * 24)))
MIN_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MIN_ADAPTIVE_WINDOW_HOURS', '2'))
MAX_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MAX_ADAPTIVE_WINDOW_HOURS', str(MAX_BASE_WINDOW_DAYS * 24)))
ADAPTIVE_TARGET_ROWS = int(os.environ.get('ADAPTIVE_TARGET_ROWS', '1500'))
ADAPTIVE_LOW_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_LOW_WATERMARK_ROWS', '300'))
ADAPTIVE_HIGH_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_HIGH_WATERMARK_ROWS', '5000'))

# Debug logging at module init
logging.debug(f"ENV CONFIG: BASE_WINDOW_DAYS={DEFAULT_BASE_WINDOW_DAYS}, BACKFILL_MODE={BACKFILL_MODE}, BACKFILL_BASE_WINDOW_DAYS={BACKFILL_BASE_WINDOW_DAYS}, MAX_BASE_WINDOW_DAYS={MAX_BASE_WINDOW_DAYS}")

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


def choose_window_days(now, latest_window_end):
    """Legacy wrapper kept for compatibility; adaptive logic now works in hours."""
    _ = now
    _ = latest_window_end
    hours = max(BASE_WINDOW_HOURS, MIN_ADAPTIVE_WINDOW_HOURS)
    return hours / 24.0


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
        if BACKFILL_MODE:
            bootstrap_hours = min(max(BACKFILL_BASE_WINDOW_DAYS * 24.0, min_hours), max_hours)
            logging.info(f"Adaptive window bootstrap (backfill mode): {bootstrap_hours:.2f}h")
            return bootstrap_hours
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


def _body_to_string(body):
    if body is None:
        return None
    if isinstance(body, str):
        return body
    try:
        if isinstance(body, dict) and 'content' in body:
            parts = []
            def walk(node):
                if node is None:
                    return
                if isinstance(node, str):
                    parts.append(node)
                    return
                if isinstance(node, dict):
                    if 'text' in node and isinstance(node['text'], str):
                        parts.append(node['text'])
                    for k in ('content', 'content_list'):
                        if k in node and isinstance(node[k], list):
                            for child in node[k]:
                                walk(child)
                    return
                if isinstance(node, list):
                    for item in node:
                        walk(item)
            walk(body.get('content'))
            if parts:
                return ' '.join(parts)
    except Exception:
        pass
    try:
        import json
        return json.dumps(body, ensure_ascii=False)
    except Exception:
        return str(body)


def fetch_and_sync_jira_comments_nightly():
    config = load_config()
    if config is None:
        return

    jira_base_url = 'https://consoleconnect.atlassian.net'
    search_url = f"{jira_base_url}/rest/api/3/search/jql"
    username = config.get('jira_user')
    api_token = config.get('jira_api_token')

    run_id = str(uuid.uuid4())
    table_id = 'JiraComments'
    temp_table_id = 'JiraComments_temp'
    temp_table_id_run = f"{temp_table_id}_{run_id[:8]}"
    progress_table_id = 'JiraComments_progress'
    dataset_id = 'GSO'
    pipeline_name = "GCP - JiraCommentsNightly"
    client = None
    run_started = None
    total_rows = 0
    final_status = "ERROR"
    final_level = "ERROR"
    final_message = "Pipeline did not complete"
    final_error_code = None

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
        logging.info(f"Projects for comments nightly run: {projects}")

        bq_schema = [
            bigquery.SchemaField('Issue_Key','STRING'),
            bigquery.SchemaField('Comment_ID','STRING'),
            bigquery.SchemaField('Author_Account_ID','STRING'),
            bigquery.SchemaField('Author_Display_Name','STRING'),
            bigquery.SchemaField('Created','TIMESTAMP'),
            bigquery.SchemaField('Updated','TIMESTAMP'),
            bigquery.SchemaField('Body','STRING'),
            bigquery.SchemaField('Visibility_Type','STRING'),
            bigquery.SchemaField('Visibility_Value','STRING'),
            bigquery.SchemaField('SyncTime','TIMESTAMP'),
        ]

        headers = {'Accept': 'application/json'}

        def fetch_issue_keys_paginated(jql):
            start_at = 0
            max_results = 100
            total = float('inf')
            keys = []
            while start_at < total:
                try:
                    params = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': 'key'}
                    resp = requests.get(search_url, headers=headers, auth=(username, api_token), params=params, timeout=30)
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
                    break
            return keys

        def fetch_comments_for_issue(issue_key):
            url = f"{jira_base_url}/rest/api/2/issue/{issue_key}/comment"
            start = 0
            size = 100
            out = []
            attempts = 0
            while True:
                try:
                    r = requests.get(url, auth=(username, api_token), params={'startAt': start, 'maxResults': size}, timeout=60)
                    if r.status_code == 429:
                        ra = int(r.headers.get('Retry-After', 10) or 10)
                        sleep_for = ra + random.uniform(0, JITTER_MAX_SECONDS)
                        logging.warning(f"429 comments {issue_key} startAt={start}; sleeping {sleep_for:.1f}s")
                        time.sleep(sleep_for)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    cm = data.get('comments', [])
                    out.extend(cm)
                    total = data.get('total', len(out))
                    if start + len(cm) >= total:
                        break
                    start += len(cm)
                    time.sleep(0.02 + random.uniform(0, 0.05))
                except Exception:
                    attempts += 1
                    if attempts >= 5:
                        break
                    back = min(60, 2 ** attempts) + random.uniform(0, JITTER_MAX_SECONDS)
                    time.sleep(back)
            return out

        def generate_rows(issue_keys, ws_bound, we_bound):
            now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            # Ensure bounds are naive for comparison with parsed timestamps
            ws_naive = ws_bound.replace(tzinfo=None) if getattr(ws_bound, 'tzinfo', None) else ws_bound
            we_naive = we_bound.replace(tzinfo=None) if getattr(we_bound, 'tzinfo', None) else we_bound
            
            # Handle empty issue_keys
            if not issue_keys:
                return
            
            # Parallel fetching of comments
            max_workers = min(10, len(issue_keys))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_key = {executor.submit(fetch_comments_for_issue, key): key for key in issue_keys}
                
                for future in as_completed(future_to_key):
                    key = future_to_key[future]
                    try:
                        comments = future.result()
                    except Exception as e:
                        logging.warning(f"Failed to fetch comments for {key}: {e}")
                        continue
                    
                    for c in comments:
                        created = convert_timestamp(c.get('created'))
                        updated = convert_timestamp(c.get('updated'))
                        ref = updated or created
                        if not ref:
                            continue
                        try:
                            ref_dt = datetime.strptime(ref, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            continue
                        if not (ws_naive <= ref_dt < we_naive):
                            continue
                        a = c.get('author', {})
                        vis = c.get('visibility', {})
                        yield {
                            'Issue_Key': key,
                            'Comment_ID': c.get('id'),
                            'Author_Account_ID': a.get('accountId'),
                            'Author_Display_Name': a.get('displayName'),
                            'Created': created,
                            'Updated': updated,
                            'Body': _body_to_string(c.get('body')),
                            'Visibility_Type': vis.get('type'),
                            'Visibility_Value': vis.get('value'),
                            'SyncTime': now_str,
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
                logging.info(f"JQL (comments nightly window): {jql_window}")

                window_failed = False

                issue_keys = fetch_issue_keys_paginated(jql_window)
                logging.info(f"Issue keys fetched for comments: {len(issue_keys)}")

                rows_to_insert = []
                rows_this_window = 0
                batch = 1000
                for row in generate_rows(issue_keys, ws, we):
                    rows_to_insert.append(row)
                    if len(rows_to_insert) >= batch:
                        if not insert_rows_resilient(client, dataset_id, temp_table_id_run, rows_to_insert, bq_schema):
                            mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
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
                        window_failed = True
                    if window_failed:
                        break
                    rows_this_window += len(rows_to_insert)
                    total_rows += len(rows_to_insert)

                if window_failed:
                    break

                merge = f"""
                                    MERGE `{dataset_id}.{table_id}` T USING (SELECT DISTINCT * FROM `{dataset_id}.{temp_table_id_run}`) S
                  ON T.Comment_ID=S.Comment_ID AND T.Updated=S.Updated
                                    WHEN MATCHED THEN UPDATE SET T.Issue_Key=S.Issue_Key,T.Author_Account_ID=S.Author_Account_ID,T.Author_Display_Name=S.Author_Display_Name,T.Created=S.Created,T.Body=S.Body,T.Visibility_Type=S.Visibility_Type,T.Visibility_Value=S.Visibility_Value,T.SyncTime=S.SyncTime,T.IsDeleted=FALSE,T.DeletedAt=NULL
                                    WHEN NOT MATCHED THEN INSERT (Issue_Key,Comment_ID,Author_Account_ID,Author_Display_Name,Created,Updated,Body,Visibility_Type,Visibility_Value,SyncTime,IsDeleted,DeletedAt)
                                    VALUES (S.Issue_Key,S.Comment_ID,S.Author_Account_ID,S.Author_Display_Name,S.Created,S.Updated,S.Body,S.Visibility_Type,S.Visibility_Value,S.SyncTime,FALSE,NULL)
                """
                try:
                    execute_bq_query_with_retry(client, merge, max_retries=5, initial_delay=10.0)
                    logging.info("Merged comments temp table into final table.")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'complete', row_count=rows_this_window)
                    try:
                        client.query(f"TRUNCATE TABLE `{dataset_id}.{temp_table_id_run}`").result()
                    except Exception as truncate_err:
                        logging.warning(f"Failed to truncate temp table after merge: {truncate_err}")
                except Exception as e:
                    logging.error(f"Merge failed: {e}")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=rows_this_window)

                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Window complete", status="SUCCESS", rows_merged=int(rows_this_window), duration_seconds=duration_seconds, window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))
                # Continue to next window if backlog remains

                if ENABLE_SOFT_DELETE_RECONCILIATION:
                        # Reconciliation step: soft-delete comments for deleted/missing tickets; restore when ticket is active.
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
                        logging.warning("Soft-delete reconciliation disabled; skipping comments nightly delete-marking")

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
            WHERE PipelineName = 'GCP - JiraCommentsNightly'
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    try:
        fetch_and_sync_jira_comments_nightly()
        return {"status": "success", "message": "Jira comments nightly sync completed"}, 200
    except Exception as e:
        logging.error(f"Cloud Function failed: {e}")
        return {"status": "error", "message": str(e)}, 500
