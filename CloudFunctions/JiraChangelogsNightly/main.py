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
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

setup_root_logging()

JITTER_MAX_SECONDS = 0.3
MIN_PROGRESS_WINDOW_SEC = 600
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


def select_window(client, dataset_id, table_id, project, base_days=1):
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

    end = start + timedelta(days=base_days)
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
    username = config.get('jira_user')
    api_token = config.get('jira_api_token')

    table_id = 'JiraChangelog'
    temp_table_id = 'JiraChangelog_temp'
    progress_table_id = 'JiraChangelog_progress'
    dataset_id = 'GSO'
    pipeline_name = "GCP - JiraChangelogsNightly"

    run_id = str(uuid.uuid4())
    client = None

    try:
        run_started = datetime.now(timezone.utc)
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

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
            bigquery.SchemaField("Transitioned_From", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_To", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_By_Account_ID", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Transitioned_By_Display_Name", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
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
                    resp = requests.get(search_url, headers=headers, auth=(username, api_token), params=params, timeout=60)
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

        def fetch_issue_history(issue_key):
            """Fetch changelog history for an issue with expand=changelog."""
            url = f"{jira_base_url}/rest/api/2/issue/{issue_key}"
            attempts = 0
            while attempts < 5:
                try:
                    params = {'expand': 'changelog'}
                    r = requests.get(url, auth=(username, api_token), params=params, timeout=60)
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
            for key in issue_keys:
                issue_data = fetch_issue_history(key)
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
                    for item in items:
                        field = item.get('field')
                        if field == 'status':
                            yield {
                                "Issue_Key": key,
                                "History_ID": history_id,
                                "Transition_Timestamp": created_ts,
                                "Transitioned_From": item.get('fromString'),
                                "Transitioned_To": item.get('toString'),
                                "Transitioned_By_Account_ID": author.get('accountId'),
                                "Transitioned_By_Display_Name": author.get('displayName'),
                                "SyncTime": now_str,
                            }

        total_rows = 0
        for proj in projects:
            logging.info(f"Starting nightly window selection for project {proj}")
            proj_safe = proj.replace(' ', '_').replace('&', 'and').replace('-', '_')
            temp_table_id_proj = f"{temp_table_id}_{proj_safe}"
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
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Window in_progress", status="RUNNING", window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))

                proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
                time_clause = f"updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                jql_window = f"({proj_clause}) AND {time_clause}"
                logging.info(f"JQL (changelogs nightly window): {jql_window}")

                window_failed = False
                if not create_or_replace_temp_table(client, dataset_id, temp_table_id_proj, bq_schema):
                    logging.error("Setup failed: Could not create temp table.")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=0)
                    window_failed = True
                if not window_failed and not wait_for_table(client, dataset_id, temp_table_id_proj, retries=30, delay=2):
                    logging.error("Setup failed: Temp table not available.")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=0)
                    window_failed = True
                if window_failed:
                    break

                issue_keys = fetch_issue_keys_paginated(jql_window)
                logging.info(f"Issue keys fetched for changelogs: {len(issue_keys)}")

                rows_to_insert = []
                rows_this_window = 0
                batch = 1000
                for row in generate_rows(issue_keys, ws, we):
                    rows_to_insert.append(row)
                    if len(rows_to_insert) >= batch:
                        if not insert_rows_resilient(client, dataset_id, temp_table_id_proj, rows_to_insert, bq_schema):
                            delete_temp_table(client, dataset_id, temp_table_id_proj)
                            mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                            window_failed = True
                            break
                        rows_this_window += len(rows_to_insert)
                        total_rows += len(rows_to_insert)
                        rows_to_insert = []
                if window_failed:
                    delete_temp_table(client, dataset_id, temp_table_id_proj)
                    break
                if rows_to_insert:
                    if not insert_rows_resilient(client, dataset_id, temp_table_id_proj, rows_to_insert, bq_schema):
                        delete_temp_table(client, dataset_id, temp_table_id_proj)
                        mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                        window_failed = True
                    if window_failed:
                        break
                    rows_this_window += len(rows_to_insert)
                    total_rows += len(rows_to_insert)

                if window_failed:
                    break

                merge = f"""
                  MERGE `{dataset_id}.{table_id}` T USING (SELECT DISTINCT * FROM `{dataset_id}.{temp_table_id_proj}`) S
                  ON T.Issue_Key = S.Issue_Key AND T.History_ID = S.History_ID AND T.Transition_Timestamp = S.Transition_Timestamp
                  WHEN MATCHED THEN UPDATE SET T.Transitioned_From=S.Transitioned_From,T.Transitioned_To=S.Transitioned_To,T.Transitioned_By_Account_ID=S.Transitioned_By_Account_ID,T.Transitioned_By_Display_Name=S.Transitioned_By_Display_Name,T.SyncTime=S.SyncTime
                  WHEN NOT MATCHED THEN INSERT (Issue_Key,History_ID,Transition_Timestamp,Transitioned_From,Transitioned_To,Transitioned_By_Account_ID,Transitioned_By_Display_Name,SyncTime)
                  VALUES (S.Issue_Key,S.History_ID,S.Transition_Timestamp,S.Transitioned_From,S.Transitioned_To,S.Transitioned_By_Account_ID,S.Transitioned_By_Display_Name,S.SyncTime)
                """
                try:
                    client.query(merge).result()
                    logging.info("Merged changelogs temp table into final table.")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'complete', row_count=rows_this_window)
                except Exception as e:
                    logging.error(f"Merge failed: {e}")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=rows_this_window)

                delete_temp_table(client, dataset_id, temp_table_id_proj)

                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Window complete", status="SUCCESS", rows_merged=int(rows_this_window), duration_seconds=duration_seconds, window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))
                # Continue to next window if backlog remains

        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline finished", status="SUCCESS", rows_merged=int(total_rows), duration_seconds=duration_seconds)
    except Exception as e:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message=f"Exception: {e}", status="ERROR", error_code=getattr(e, "code", None), duration_seconds=duration_seconds)
        raise


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
