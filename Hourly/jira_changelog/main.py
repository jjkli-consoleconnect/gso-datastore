import requests
import sys, pathlib
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
import json
from google.cloud import bigquery
import logging
from datetime import datetime, timedelta, timezone
import time
import os
from concurrent.futures import ThreadPoolExecutor
import random
import uuid
from typing import Optional
from pipeline_runs_logger import log_pipeline_run

# --- Logging Buffer for BigQuery Logs ---
LOG_BUFFER = []

# Logging configuration: LOG_LEVEL env override and DEBUG support
DEBUG = str(os.environ.get('DEBUG', '')).lower() in ('1', 'true', 'yes')
_env_level = os.environ.get('LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO').upper()
_level = getattr(logging, _env_level, logging.INFO)
logging.basicConfig(level=_level, format='%(asctime)s - %(levelname)s - %(message)s')
if _level > logging.INFO:
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('google.cloud').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token and email.")
        return None

def load_base_jql(default_text: Optional[str] = None) -> Optional[str]:
    """Load base JQL from env (BASE_JQL_B64/BASE_JQL/JQL_FILE/PROJECTS_FILE) or ../JQL.txt next to Hourly."""
    # Highest precedence: env-provided JQL
    env_b64 = os.environ.get('BASE_JQL_B64')
    if env_b64:
        try:
            import base64
            decoded = base64.b64decode(env_b64).decode('utf-8').strip()
            if DEBUG:
                logging.info("[JQL_LOAD] Loaded base JQL from BASE_JQL_B64 env variable")
            if decoded:
                return decoded
        except Exception as e:
            logging.warning(f"[JQL_LOAD] Failed decoding BASE_JQL_B64: {e}")

    env_text = os.environ.get('BASE_JQL')
    if env_text and env_text.strip():
        if DEBUG:
            logging.info("[JQL_LOAD] Loaded base JQL from BASE_JQL env variable")
        return env_text.strip()

    env_path = os.environ.get('JQL_FILE') or os.environ.get('PROJECTS_FILE')
    candidates = []
    if env_path:
        candidates.append(env_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.normpath(os.path.join(script_dir, '..', 'JQL.txt')))
    candidates.append(os.path.normpath(os.path.join(script_dir, '..', '..', 'InitialSync', 'JQL.txt')))
    candidates.extend(['/config/JQL.txt', '/data/JQL.txt'])
    if DEBUG:
        logging.info(f"[JQL_LOAD] Env JQL_FILE={os.environ.get('JQL_FILE')} PROJECTS_FILE={os.environ.get('PROJECTS_FILE')} BASE_JQL=set? {'yes' if os.environ.get('BASE_JQL') else 'no'} BASE_JQL_B64=set? {'yes' if os.environ.get('BASE_JQL_B64') else 'no'}")
        logging.info(f"[JQL_LOAD] Candidate paths: {candidates}")
    for path in candidates:
        if not path:
            continue
        try:
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                    text = raw.strip('\n\r ')
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    filtered = []
                    for ln in lines:
                        u = ln.lstrip()
                        if u.startswith('#') or u.startswith('//') or u.startswith('--'):
                            continue
                        filtered.append(ln)
                    rebuilt = '\n'.join(filtered)
                    if filtered and not any('project ' in ln.lower() for ln in filtered):
                        clauses = []
                        for p in filtered:
                            if p in ('*','ALL'):
                                continue
                            if p.isupper() and ' ' not in p and '-' not in p:
                                clauses.append(f'project = {p}')
                            else:
                                clauses.append(f'project = "{p}"')
                        if clauses:
                            rebuilt = '(' + ' OR '.join(clauses) + ')'
                        else:
                            rebuilt = ''
                    logging.info(f"Loaded base JQL from: {path}")
                    return rebuilt.strip() if rebuilt else text
            else:
                if DEBUG:
                    logging.info(f"[JQL_LOAD] Skipping non-file path: {path}")
        except Exception as e:
            logging.warning(f"[JQL_LOAD] Failed reading {path}: {e}")
    if default_text:
        logging.info("Using embedded default base JQL.")
        return default_text.strip()
    logging.error("No base JQL found. Provide Hourly/JQL.txt or set JQL_FILE env var.")
    return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
            return None
    return None

def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        query = f"""
        CREATE OR REPLACE TABLE `{client.project}.{dataset_id}.{table_id}`
        (
            {', '.join(f'{f.name} {f.field_type}' for f in schema)}
        )
        """
        client.query(query).result()
        logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' created or replaced.")
        return True
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{client.project}.{dataset_id}.{table_id}': {e}")
        return False

# This function is defined but not used. Consider removing if not planned for use.
# def create_temp_table_if_not_exists(client, dataset_id, table_id, schema):
#     if not table_exists(client, dataset_id, table_id):
#         return create_or_replace_temp_table(client, dataset_id, table_id, schema)
#     return True

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' deleted.")
        return True
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{client.project}.{dataset_id}.{table_id}': {e}")
        return False
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)  # not_found_ok is supported in google-cloud-bigquery >= 1.25.0
        logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' deleted (or did not exist).")
        return True
    except TypeError:
        # For older google-cloud-bigquery versions, fallback to manual not found handling
        try:
            client.delete_table(table_ref)
            logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' deleted.")
            return True
        except Exception as e:
            if 'Not found' in str(e) or '404' in str(e):
                logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' did not exist (already deleted).")
                return True
            logging.exception(f"Error deleting temporary table '{client.project}.{dataset_id}.{table_id}': {e}")
            return False
    except Exception as e:
        if 'Not found' in str(e) or '404' in str(e):
            logging.info(f"Temporary table '{client.project}.{dataset_id}.{table_id}' did not exist (already deleted).")
            return True
        logging.exception(f"Error deleting temporary table '{client.project}.{dataset_id}.{table_id}': {e}")
        return False

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{client.project}.{dataset_id}.{table_id}")
        return True
    except Exception: # More specific exception (e.g., google.cloud.exceptions.NotFound) is better
        # logging.error(f"Table '{client.project}.{dataset_id}.{table_id}' does not exist: {e}") # 'e' not defined here
        return False

def wait_for_table(client, dataset_id, table_id, retries=10, delay=5):
    for attempt in range(retries):
        if table_exists(client, dataset_id, table_id):
            logging.info(f"Table '{client.project}.{dataset_id}.{table_id}' is now available.")
            return True
        logging.info(f"Waiting for table '{client.project}.{dataset_id}.{table_id}' to be available. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    logging.error(f"Table '{client.project}.{dataset_id}.{table_id}' is not available after {retries} attempts.")
    return False

def insert_rows_with_retry(client, dataset_id, table_id, rows, retries=5, delay=5):
    if not rows:
        logging.info(f"No rows to insert into '{client.project}.{dataset_id}.{table_id}'.")
        return True
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(f"{client.project}.{dataset_id}.{table_id}", rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into '{client.project}.{dataset_id}.{table_id}'.")
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            logging.exception(f"Error inserting rows into BigQuery: {e}")
        logging.info(f"Retrying insert rows into table '{client.project}.{dataset_id}.{table_id}' after 5 seconds. Attempt {attempt + 1}/{retries}")
        time.sleep(5)
    logging.error(f"Failed to insert rows into '{client.project}.{dataset_id}.{table_id}' after {retries} retries.")
    return False

def fetch_issue_history(jira_url, issue_key, username, api_token):
    """Fetches the history (including transitions) for a given issue."""
    # For Jira Cloud, /rest/api/2/ and /rest/api/latest/ are often interchangeable for core functionalities
    # The script uses /rest/api/2/ which is generally fine.
    url = f"{jira_url}/rest/api/2/issue/{issue_key}?expand=changelog"
    headers = {"Accept": "application/json"}
    auth = (username, api_token) # For Jira Cloud, username is typically the email address

    try:
        response = requests.get(url, headers=headers, auth=auth, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logging.error(f"Error fetching history for issue {issue_key}: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON response for issue {issue_key}: {e}")
        return None

def fetch_issue_histories_parallel(jira_url, issues, username, api_token):
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_issue_history, jira_url, issue['key'], username, api_token): issue for issue in issues}
        results = {}
        for future in futures:
            issue_key = futures[future]['key']
            try:
                results[issue_key] = future.result()
            except Exception as e:
                logging.error(f"Error fetching history for issue {issue_key} in parallel: {e}") # Added "in parallel" for clarity
    return results

def fetch_issues_with_retry(jira_search_url, headers, auth, payload, retries=5, delay=5):
    for attempt in range(retries):
        try:
            # Using jira_search_url directly as it's already fully formed
            response = requests.post(jira_search_url, headers=headers, auth=auth, data=payload, timeout=300)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            backoff = delay * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(f"Retrying API call to {jira_search_url} after {backoff:.2f} seconds. Attempt {attempt + 1}/{retries}. Error: {e}")
            time.sleep(backoff)
    logging.error(f"Failed to fetch issues from {jira_search_url} after multiple retries.")
    return None



def run_merge_query(client, dataset_id, table_id, temp_table_id):
    merge_query = f"""
        MERGE `{client.project}.{dataset_id}.{table_id}` T
        USING (
            SELECT DISTINCT
                Issue_Key, History_ID, Transition_Timestamp, Transitioned_From, Transitioned_To,
                Transitioned_By_Account_ID, Transitioned_By_Display_Name, SyncTime
            FROM `{client.project}.{dataset_id}.{temp_table_id}`
        ) S
        ON T.History_ID = S.History_ID AND T.Transition_Timestamp = S.Transition_Timestamp
        WHEN MATCHED THEN
            UPDATE SET
                T.Issue_Key = S.Issue_Key,
                T.Transitioned_From = S.Transitioned_From,
                T.Transitioned_To = S.Transitioned_To,
                T.Transitioned_By_Account_ID = S.Transitioned_By_Account_ID,
                T.Transitioned_By_Display_Name = S.Transitioned_By_Display_Name,
                T.SyncTime = S.SyncTime
        WHEN NOT MATCHED THEN
            INSERT (Issue_Key, History_ID, Transition_Timestamp, Transitioned_From, Transitioned_To, Transitioned_By_Account_ID, Transitioned_By_Display_Name, SyncTime)
            VALUES (S.Issue_Key, S.History_ID, S.Transition_Timestamp, S.Transitioned_From, S.Transitioned_To, S.Transitioned_By_Account_ID, S.Transitioned_By_Display_Name, S.SyncTime)
    """

    logging.info(f"Executing MERGE query into {client.project}.{dataset_id}.{table_id}")
    try:
        query_job = client.query(merge_query)
        query_job.result()
        logging.info("Merge query executed successfully.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        return False
    return True

# --- BigQuery Logging Mechanism ---
def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, level, message, FunctionName=None, BatchID=None, Details=None):
    log_entry = {
        # 'Timestamp' intentionally omitted; BigQuery will use its default value
        "PipelineName": pipeline_name,
        "RunID": run_id,
        "LogLevel": level,
        "Message": message,
        "FunctionName": FunctionName,
        "BatchID": BatchID,
        "Details": Details
    }
    LOG_BUFFER.append(log_entry)

def flush_logs_to_bigquery(client, dataset_id, table_id):
    for log in LOG_BUFFER:
        context = {}
        if log.get('FunctionName'):
            context['FunctionName'] = log['FunctionName']
        if log.get('BatchID'):
            context['BatchID'] = log['BatchID']
        if log.get('Details'):
            context['Details'] = log['Details']
        log_pipeline_run(client, pipeline_name=log['PipelineName'], run_id=log['RunID'], level=log['LogLevel'], message=log['Message'], status='INFO', context=context if context else None)
    LOG_BUFFER.clear()
    logging.info("All log entries successfully logged to PipelineRuns.")

def sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
    temp_table_id = f"{table_id}_temp"
    schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("History_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transition_Timestamp", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_From", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_To", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
    ]

    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, schema):
        logging.error("Failed to create or replace temporary table.")
        return False
    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error(f"Temporary table '{temp_table_id}' is not available.")
        return False

    total_issues = float('inf')
    start_at = 0
    max_results = 100
    issues_processed = 0
    batch_size = 1000
    search_api_endpoint = f"{jira_base_url}/rest/api/2/search"
    rows_inserted = 0

    while start_at < total_issues:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (username, api_token)
        payload = json.dumps({"jql": jql_query, "startAt": start_at, "maxResults": max_results, "fields": ["key"]})

        logging.info(f"Fetching issues from Jira: {search_api_endpoint} with JQL, startAt {start_at}, maxResults {max_results}")
        try:
            data = fetch_issues_with_retry(search_api_endpoint, headers, auth, payload)
            if data is None:
                logging.error(f"Repeated failures in fetching issues. Merging and exiting.")
                break
        except Exception as e:
            logging.error(f"Unexpected error during issue fetch: {e}")
            start_at += max_results
            continue

        issues = data.get('issues', [])
        total_issues = data.get('total', 0)

        if not issues:
            if start_at == 0:
                logging.info(f"No issues found for JQL: {jql_query}")
            else:
                logging.info(f"No more issues found on page starting at {start_at}.")
            break

        logging.info(f"Fetched {len(issues)} issues. Total according to Jira: {total_issues}. Current offset: {start_at}")

        rows_to_insert = []
        # Fetch histories in parallel for the current page of issues
        issue_histories = fetch_issue_histories_parallel(jira_base_url, issues, username, api_token)

        for issue_data in issues:
            issue_key = issue_data.get('key')
            if not issue_key:
                logging.warning(f"Issue missing key in search results. Data: {issue_data}. Skipping.")
                continue

            issue_history_detail = issue_histories.get(issue_key)

            if issue_history_detail is None:
                logging.warning(f"Could not retrieve history for issue {issue_key}. Skipping.")
                continue

            histories = issue_history_detail.get('changelog', {}).get('histories', [])

            for history_entry in histories:
                history_id = history_entry.get('id')
                author = history_entry.get('author', {})
                created_timestamp = convert_timestamp(history_entry.get('created'))
                if not created_timestamp:
                    logging.warning(f"Skipping history entry {history_id} for issue {issue_key} due to invalid creation timestamp.")
                    continue
                for item in history_entry.get('items', []):
                    if item.get('fieldId') == 'status' or item.get('field') == 'status':
                        rows_to_insert.append({
                            "Issue_Key": issue_key,
                            "History_ID": history_id,
                            "Transition_Timestamp": created_timestamp,
                            "Transitioned_From": item.get('fromString'),
                            "Transitioned_To": item.get('toString'),
                            "Transitioned_By_Account_ID": author.get('accountId'),
                            "Transitioned_By_Display_Name": author.get('displayName'),
                            "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                        })

            # Insert rows in batches to BigQuery temp table
            if len(rows_to_insert) >= batch_size:
                if insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                    rows_inserted += len(rows_to_insert)
                else:
                    logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                    delete_temp_table(client, dataset_id, temp_table_id)
                    return False
                rows_to_insert = []

        # Insert any remaining rows after processing all issues on the page
        if rows_to_insert:
            if insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                rows_inserted += len(rows_to_insert)
            else:
                logging.error(f"Failed to insert remaining rows into temp table. Stopping processing.")
                delete_temp_table(client, dataset_id, temp_table_id)
                return False

        issues_processed += len(issues)
        logging.info(f"Processed details for {len(issues)} issues. Total issues processed so far: {issues_processed} out of {total_issues}")
        remaining_issues = total_issues - issues_processed
        logging.info(f"Remaining issues to process: {remaining_issues}")
        start_at += max_results  # Advance to next page
        time.sleep(1)

    # Merge temp table into final table (upsert logic)
    if rows_inserted > 0:
        run_merge_query(client, dataset_id, table_id, temp_table_id)
    delete_temp_table(client, dataset_id, temp_table_id)
    return int(rows_inserted)

# This function is defined but not used. Consider removing if not planned for use.
# def run_query_with_retry(client, query, retries=5, delay=5):
#     for attempt in range(retries):
#         try:
#             client.query(query).result()
#             return True
#         except Exception as e:
#             logging.warning(f"Retrying query after {delay} seconds. Attempt {attempt + 1}/{retries}. Error: {e}")
#             time.sleep(delay)
#     logging.error("Failed to execute query after multiple retries.")
#     return False --test

def main():
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration. Exiting.")
        return

    jira_base_url = 'https://consoleconnect.atlassian.net'
    base_default = (
        '('\
        'project = "GS&O Data Analytics" OR '\
        'project = "GS&O Tool Automation" OR '\
        'project = "GS&O Knowledge Consolidation" OR '\
        'project = "Google Contact Center AI Solution" OR '\
        'project = TAC OR '\
        'project = "VOICE - CE" OR '\
        'project = "IOT CE" OR '\
        'project = "Console Application Support" OR '\
        'project = "Console Connect Provisioning" OR '\
        'project = "Global Service Delivery Team" OR '\
        'project = "Transmission TX-CE" OR '\
        'project = "Mobility SMS - CE" OR '\
        'project = "Managed Security Services" OR '\
        'project = "Vendor Management Escalations" OR '
        'project = "Customer Success Management" '
        ')'
    )
    base_jql = load_base_jql(default_text=base_default)
    logging.info(f"Resolved base_jql for hourly changelog job: {base_jql}")
    if not base_jql:
        return
    jql_query = f"{base_jql} AND status CHANGED DURING (-1h, now())"
    # Window for CHANGED DURING is last hour relative to run start
    run_started = datetime.now(timezone.utc)
    jql_window_start = run_started - timedelta(hours=1)
    jql_window_end = run_started

    username = 'jjkli@consoleconnect.com'
    logging.info(f"Using Jira username: {username}")

    api_token = config.get('jira_api_token')
    if not api_token:
        logging.error("Jira API token not found in config.json. Exiting.")
        return

    dataset_id = 'GSO'
    table_id = 'JiraChangelog'
    log_table_id = 'PipelineRuns'
    pipeline_name = "jira_changelog"
    run_id = str(uuid.uuid4())

    try:
        client = bigquery.Client()
        logging.info(f"Successfully connected to BigQuery project: {client.project}")
    except Exception as e:
        logging.error(f"Failed to initialize BigQuery client: {e}")
        log_to_bigquery(None, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Failed to initialize BigQuery client: {e}", FunctionName="main")
        return

    # Log pipeline start
    log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline started", FunctionName="main")
    try:
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")
        rows_merged = sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client)
        if rows_merged and rows_merged > 0:
            logging.info("Successfully synced transitions history to BigQuery.")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Successfully synced transitions history to BigQuery", FunctionName="main")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline finished", status="SUCCESS", window_start=jql_window_start, window_end=jql_window_end, rows_merged=int(rows_merged))
        else:
            logging.error("Failed to sync transition history to BigQuery.")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", "Failed to sync transition history to BigQuery", FunctionName="main")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message="Failed to sync transition history to BigQuery", status="ERROR")
    except Exception as e:
        logging.exception(f"Pipeline run failed: {e}")
        log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Pipeline run failed: {e}", FunctionName="main", Details=str(e))
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message=f"Exception: {e}", status="ERROR", error_code=getattr(e, "code", None))

    # Log pipeline end
    log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline finished", FunctionName="main")

    # At the end, flush all logs to BigQuery in a batch
    flush_logs_to_bigquery(client, dataset_id, log_table_id)

if __name__ == "__main__":
    main()