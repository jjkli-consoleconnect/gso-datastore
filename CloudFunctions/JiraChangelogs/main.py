"""
Cloud Function: Jira Changelogs Sync
Syncs Jira status change history from consoleconnect.atlassian.net to BigQuery.
Routes through VPC to access Jira behind VPN.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import uuid
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, secretmanager
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError
import functions_framework

# Import shared helper functions from local copy
from jira_helpers import (
    load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table, 
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

# Setup logging
setup_root_logging()

# Jitter used when sleeping after 429s
JITTER_MAX_SECONDS = 0.3

# Rate limiting settings (Jira Cloud: ~180 req/min = ~3 req/sec)
JIRA_RATE_LIMIT_PAUSE_SEC = 0.4  # Pause between paginated searches


def handle_429_backoff(response, attempt=1, max_attempts=3):
    """Handle 429 rate limit with exponential backoff."""
    if response.status_code != 429 or attempt >= max_attempts:
        return False
    retry_after = int(response.headers.get('Retry-After', 30) or 30)
    backoff_time = min(retry_after * (2 ** (attempt - 1)), 120)  # Cap at 2 minutes
    wait_time = backoff_time + random.uniform(0, JITTER_MAX_SECONDS)
    logging.warning(f"429 Rate limit (attempt {attempt}/{max_attempts}). Waiting {wait_time:.1f}s")
    time.sleep(wait_time)
    return True


def create_session_with_retries():
    """Create a requests Session with connection pooling and retry strategy."""
    session = requests.Session()
    
    # Configure retry strategy for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # exponential backoff: 1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    # Apply to both http and https - increased pool to match concurrency
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=30, pool_maxsize=30)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session


def send_error_email(error_message, project_id="pccw-internal-virtual-agent"):
    """Send error notification. Try SendGrid (if configured), fall back to SMTP."""
    try:
        recipient = get_secret("jira-sync-alert-recipient", project_id)

        # Try SendGrid first
        try:
            sendgrid_api_key = get_secret("jira-sync-sendgrid-api-key", project_id)
        except Exception:
            sendgrid_api_key = None

        if sendgrid_api_key:
            try:
                from_email = get_secret("jira-sync-alert-email", project_id)
            except Exception:
                from_email = f"no-reply@{project_id}.iam.gserviceaccount.com"

            payload = {
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": {"email": from_email},
                "subject": "⚠️ Jira Changelogs Sync FAILED",
                "content": [{"type": "text/plain", "value": (
                    f"Jira Changelogs Sync has FAILED.\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\nFunction: jira-changelogs-sync\n\nError Details:\n{error_message}\n\nCheck Cloud Function logs: https://console.cloud.google.com/functions/details/europe-west2/jira-changelogs-sync?project={project_id}"
                )}]
            }
            headers = {"Authorization": f"Bearer {sendgrid_api_key}", "Content-Type": "application/json"}
            try:
                r = requests.post("https://api.sendgrid.com/v3/mail/send", headers=headers, json=payload, timeout=10)
                if r.status_code >= 300:
                    logging.error(f"SendGrid send failed ({r.status_code}): {r.text}")
                else:
                    logging.info("Error notification sent via SendGrid")
                    return
            except Exception as ex:
                logging.error(f"SendGrid send exception: {ex}")

        # Fallback to SMTP
        try:
            smtp_user = get_secret("jira-sync-alert-email", project_id)
            smtp_password = get_secret("jira-sync-alert-password", project_id)
        except Exception:
            smtp_user = None
            smtp_password = None

        if smtp_user and smtp_password:
            try:
                msg = MIMEMultipart()
                msg['From'] = smtp_user
                msg['To'] = recipient
                msg['Subject'] = "⚠️ Jira Changelogs Sync FAILED"
                body = (
                    f"Jira Changelogs Sync has FAILED.\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\nFunction: jira-changelogs-sync\n\nError Details:\n{error_message}\n\nCheck Cloud Function logs: https://console.cloud.google.com/functions/details/europe-west2/jira-changelogs-sync?project={project_id}"
                )
                msg.attach(MIMEText(body, 'plain'))
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                logging.info("Error notification email sent via SMTP")
                return
            except Exception as ex:
                logging.error(f"SMTP send failed: {ex}")

        logging.error("No email provider configured or all providers failed to send the error notification")
    except Exception as e:
        logging.error(f"Failed to send error notification: {e}")


def get_secret(secret_id, project_id="pccw-internal-virtual-agent"):
    """Retrieve secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')


def load_config():
    """Load Jira config from Secret Manager instead of config.json."""
    try:
        api_token = get_secret("jira-api-token")
        user_email = get_secret("jira-user-email")
        return {
            'jira_api_token': api_token,
            'jira_user': user_email
        }
    except Exception as e:
        logging.error(f"Failed to load config from Secret Manager: {e}")
        return None


def ensure_changelog_columns(client, dataset_id, table_id):
    """Ensure generic changelog columns exist so non-status changes can be stored safely."""
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


def fetch_issue_history(issue_key, username, api_token, session):
    """Fetch issue with changelog expanded."""
    url = f"https://consoleconnect.atlassian.net/rest/api/3/issue/{issue_key}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)
    params = {'expand': 'changelog'}
    
    try:
        resp = session.get(url, headers=headers, auth=auth, params=params, timeout=30)
        if resp.status_code == 429:
            ra = int(resp.headers.get('Retry-After', 30) or 30)
            logging.warning(f"429 on history fetch for {issue_key}; sleeping {ra}s")
            time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout fetching history for {issue_key}")
        return None
    except Exception as e:
        logging.warning(f"Error fetching history for {issue_key}: {e}")
        return None


def fetch_issue_histories_parallel(issue_keys, username, api_token, session, max_workers=10):
    """Fetch histories for multiple issues in parallel."""
    histories_by_issue = {}
    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(issue_keys))) as executor:
            future_map = {
                executor.submit(fetch_issue_history, key, username, api_token, session): key
                for key in issue_keys
            }
            for future in as_completed(future_map):
                issue_key = future_map[future]
                try:
                    result = future.result()
                    if result:
                        histories_by_issue[issue_key] = result
                except Exception as e:
                    logging.warning(f"Failed to fetch history for {issue_key}: {e}")
    except Exception as e:
        logging.error(f"Error in fetch_issue_histories_parallel: {e}")
    
    return histories_by_issue


def fetch_and_sync_jira_changelog():
    """Main sync function - same logic as local script."""
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    username = config.get('jira_user', 'jjkli@consoleconnect.com')
    api_token = config.get('jira_api_token')
    
    table_id = 'JiraChangelog'
    temp_table_id = 'JiraChangelog_temp'
    pipeline_name = "GCP - JiraChangelogs"
    
    run_id = str(uuid.uuid4())
    client = None
    
    try:
        run_started = datetime.now(timezone.utc)
        
        # Use UAT project for BigQuery where GSO dataset exists
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        project_id = client.project
        dataset_id = 'GSO'

        ensure_changelog_columns(client, dataset_id, table_id)
        
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

        # Load base JQL
        base_default = (
            '('\
            'project = "GS&O Data Analytics" OR '\
            'project = "Customer Success Management" OR '\
            'project = "GS&O Tool Automation" OR '\
            'project = "GS&O Knowledge Consolidation" OR '\
            'project = TAC OR '\
            'project = "VOICE - CE" OR '\
            'project = "IOT CE" OR '\
            'project = "Console Application Support" OR '\
            'project = "Console Connect Provisioning" OR '\
            'project = "Global Service Delivery Team" OR '\
            'project = "Transmission TX-CE" OR '\
            'project = "Mobility SMS - CE" OR '\
            'project = "Managed Security Services" OR '\
            'project = Sherbet OR '\
            'project = "Google Contact Center AI Solution" OR '\
            'project = "QMS Documentation" OR '\
            'project = "Operational Case Reviews" OR '\
            'project = "IT Helpdesk" OR '\
            'project = "Vendor Verification Team" OR '\
            'project = "GS&O Strategic Initiatives" '
            ')'
        )
        base_jql = load_base_jql(default_text=base_default)
        logging.info(f"Resolved base_jql: {base_jql}")
        
        if not base_jql:
            # Log and mark pipeline as ERROR before exiting
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="No base JQL resolved",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return

        # Optimized single-pass approach: capture ANY activity in last 30 minutes
        # Includes: field updates, resolutions, and new comments (which capture all changelog activity)
        jql_any_activity = build_jql(base_jql, "(updated >= -30m OR resolutiondate >= -30m OR comment.updated >= -30m)", joiner='AND')
        logging.info(f"JQL (any activity in last 30m): {jql_any_activity}")

        # BigQuery schema
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
        ]
        
        if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
            logging.error("Setup failed: Could not create temp table.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Could not create temp table",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error("Setup failed: Temp table not available.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Temp table not available",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return
        rows_to_insert = []
        issue_keys_total = set()

        # Create persistent session with connection pooling
        session = create_session_with_retries()
        
        def search_issue_keys_paginated(jql: str, label: str):
            """Fetch ALL matching issue keys with pagination. CRITICAL: Prevents data loss!"""
            all_keys = []
            start_at = 0
            max_results = 100
            headers_local = {'Accept': 'application/json'}
            auth_local = (username, api_token)
            attempt = 0
            max_attempts = 3
            
            while True:
                params_local = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': 'key'}
                try:
                    resp = session.get(jira_url, headers=headers_local, auth=auth_local, params=params_local, timeout=60)
                    
                    if resp.status_code == 429:
                        if handle_429_backoff(resp, attempt + 1, max_attempts):
                            attempt += 1
                            continue
                        else:
                            logging.error(f"Failed after {max_attempts} 429 attempts on {label}")
                            break
                    
                    resp.raise_for_status()
                    attempt = 0  # Reset on success
                    
                    data_local = resp.json()
                    issues_local = data_local.get('issues', [])
                    if not issues_local:
                        break
                    
                    all_keys.extend([i.get('key') for i in issues_local if i.get('key')])
                    total = data_local.get('total', 0)
                    
                    if start_at + max_results >= total:
                        break
                    
                    start_at += max_results
                    time.sleep(JIRA_RATE_LIMIT_PAUSE_SEC)  # Respect rate limits
                    
                except requests.exceptions.Timeout:
                    logging.warning(f"Timeout fetching keys for {label} at startAt={start_at}")
                    break
                except Exception as e:
                    logging.error(f"Error fetching keys for {label}: {e}")
                    break
            
            logging.info(f"{label}: Fetched {len(all_keys)} total issue keys (paginated)")
            return all_keys

        # Search for issues with any activity - now WITH PAGINATION
        all_issue_keys = search_issue_keys_paginated(jql_any_activity, 'changelog_activity')
        try:
            data = {'issues': [{'key': k} for k in all_issue_keys]}
            issues = data.get('issues', [])
            for issue in issues:
                issue_keys_total.add(issue.get('key'))
            logging.info(f"Status search fetched {len(issue_keys_total)} issue keys")
        except Exception as e:
            logging.error(f"Status search error: {e}")
            return

        if not issue_keys_total:
            logging.info("No issues found with status changes")
            delete_temp_table(client, dataset_id, temp_table_id)
            window_start_dt = run_started - timedelta(minutes=30)
            window_end_dt = run_started
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="INFO",
                message="Pipeline finished (no data)",
                status="SUCCESS",
                window_start=window_start_dt,
                window_end=window_end_dt,
                rows_merged=0,
                duration_seconds=duration_seconds,
            )
            return

        # Fetch histories in parallel (session already created above)
        issue_key_list = list(issue_keys_total)
        histories_by_issue = fetch_issue_histories_parallel(issue_key_list, username, api_token, session, max_workers=10)

        # Close session to release connections
        session.close()

        transitions_count = 0
        for issue_key, issue in histories_by_issue.items():
            changelog = issue.get('changelog', {})
            histories = changelog.get('histories', [])
            
            for history in histories:
                history_id = history.get('id')
                created_str = history.get('created')
                created_ts = convert_timestamp(created_str)
                author = history.get('author', {})
                
                items = history.get('items', [])
                for item_index, item in enumerate(items):
                    field = item.get('field')
                    row = {
                        "Issue_Key": issue_key,
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
                        "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    }
                    rows_to_insert.append(row)
                    transitions_count += 1

        logging.info(f"Extracted {transitions_count} status transitions")

        if rows_to_insert:
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, bq_schema, retries=5, delay=5):
                logging.error("Failed to insert rows into temp table after retries.")
                delete_temp_table(client, dataset_id, temp_table_id)
                return

        # Merge temp table into final table
        try:
            merge_query = f'''
                MERGE `{dataset_id}.{table_id}` T
                USING `{dataset_id}.{temp_table_id}` S
                ON T.Issue_Key = S.Issue_Key
                   AND T.History_ID = S.History_ID
                   AND T.Transition_Timestamp = S.Transition_Timestamp
                   AND COALESCE(T.Changed_Field, 'status') = COALESCE(S.Changed_Field, 'status')
                   AND COALESCE(T.Change_Item_Index, 0) = COALESCE(S.Change_Item_Index, 0)
                WHEN MATCHED THEN UPDATE SET
                    T.Changed_Field = S.Changed_Field,
                    T.Changed_FieldType = S.Changed_FieldType,
                    T.Change_Item_Index = S.Change_Item_Index,
                    T.From_ID = S.From_ID,
                    T.From_Value = S.From_Value,
                    T.To_ID = S.To_ID,
                    T.To_Value = S.To_Value,
                    T.Transitioned_From = S.Transitioned_From,
                    T.Transitioned_To = S.Transitioned_To,
                    T.Transitioned_By_Account_ID = S.Transitioned_By_Account_ID,
                    T.Transitioned_By_Display_Name = S.Transitioned_By_Display_Name,
                    T.SyncTime = S.SyncTime,
                    T.IsDeleted = FALSE,
                    T.DeletedAt = NULL
                WHEN NOT MATCHED THEN INSERT (Issue_Key, History_ID, Transition_Timestamp, Changed_Field, Changed_FieldType, Change_Item_Index, From_ID, From_Value, To_ID, To_Value, Transitioned_From, Transitioned_To, Transitioned_By_Account_ID, Transitioned_By_Display_Name, SyncTime, IsDeleted, DeletedAt)
                VALUES (S.Issue_Key, S.History_ID, S.Transition_Timestamp, S.Changed_Field, S.Changed_FieldType, S.Change_Item_Index, S.From_ID, S.From_Value, S.To_ID, S.To_Value, S.Transitioned_From, S.Transitioned_To, S.Transitioned_By_Account_ID, S.Transitioned_By_Display_Name, S.SyncTime, FALSE, NULL)
            '''
            client.query(merge_query).result()
            logging.info(f"Merged temp table into '{dataset_id}.{table_id}'.")
        except Exception as e:
            logging.error(f"Error merging temp table: {e}")

        delete_temp_table(client, dataset_id, temp_table_id)

        # Log pipeline end
        window_start_dt = run_started - timedelta(minutes=30)
        window_end_dt = run_started
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline finished",
            status="SUCCESS",
            window_start=window_start_dt,
            window_end=window_end_dt,
            rows_merged=transitions_count,
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
    """Cloud Function HTTP entry point."""
    # Cleanup: Mark stale RUNNING entries as ERROR (older than 10 minutes)
    try:
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        cleanup_query = '''
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = 'GCP - JiraChangelogs'
            AND Status = 'RUNNING'
            AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")
    
    try:
        fetch_and_sync_jira_changelog()
        return {"status": "success", "message": "Jira changelog sync completed"}, 200
    except Exception as e:
        error_msg = f"Cloud Function failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        # Send error notification email
        send_error_email(error_msg)
        return {"status": "error", "message": str(e)}, 500
