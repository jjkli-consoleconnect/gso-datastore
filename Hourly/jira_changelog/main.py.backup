"""
Hourly Jira Changelog Sync (Refactored) - uses shared helpers
Syncs hourly changelog events (status transitions) from Jira to BigQuery.
"""
import requests
import sys
import pathlib
import json
import logging
from datetime import datetime, timedelta, timezone
import time
import os
from concurrent.futures import ThreadPoolExecutor
import random
import uuid
from typing import Optional
from google.cloud import bigquery

# Setup repository path
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Import shared helpers
from shared.jira_helpers import load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table, delete_temp_table
from shared.logging_config import setup_root_logging
from shared.pipeline_runs_logger import log_pipeline_run

# Setup logging
setup_root_logging()

# --- Logging Buffer for BigQuery Logs ---
LOG_BUFFER = []


def load_config():
    """Load Jira config from config.json."""
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token and email.")
        return None


def table_exists(client, dataset_id, table_id):
    """Check if a BigQuery table exists."""
    try:
        client.get_table(f"{client.project}.{dataset_id}.{table_id}")
        return True
    except Exception:
        return False


def wait_for_table(client, dataset_id, table_id, retries=10, delay=5):
    """Wait for table to become available."""
    for attempt in range(retries):
        if table_exists(client, dataset_id, table_id):
            logging.info(f"Table '{client.project}.{dataset_id}.{table_id}' is now available.")
            return True
        logging.info(f"Waiting for table '{client.project}.{dataset_id}.{table_id}' to be available. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    logging.error(f"Table '{client.project}.{dataset_id}.{table_id}' is not available after {retries} attempts.")
    return False


def insert_rows_with_retry(client, dataset_id, table_id, rows, retries=5, delay=5):
    """Insert rows into BigQuery with retries."""
    if not rows:
        logging.info(f"No rows to insert into '{dataset_id}.{table_id}'.")
        return True
    
    for attempt in range(retries):
        try:
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into '{dataset_id}.{table_id}'.")
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            logging.exception(f"Error inserting rows into BigQuery: {e}")
        logging.info(f"Retrying insert rows into table '{dataset_id}.{table_id}' after 5 seconds. Attempt {attempt + 1}/{retries}")
        time.sleep(5)
    logging.error(f"Failed to insert rows into '{dataset_id}.{table_id}' after {retries} retries.")
    return False


def fetch_issue_history(jira_url, issue_key, username, api_token):
    """Fetch the history (transitions) for a given issue."""
    url = f"{jira_url}/rest/api/2/issue/{issue_key}?expand=changelog"
    headers = {"Accept": "application/json"}
    auth = (username, api_token)

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
    """Fetch histories for multiple issues in parallel."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_issue_history, jira_url, issue['key'], username, api_token): issue for issue in issues}
        results = {}
        for future in futures:
            issue_key = futures[future]['key']
            try:
                results[issue_key] = future.result()
            except Exception as e:
                logging.error(f"Error fetching history for issue {issue_key} in parallel: {e}")
    return results


def fetch_issues_with_retry(jira_search_url, headers, auth, payload, retries=5, delay=5):
    """Fetch issues from Jira with retries."""
    params = payload if isinstance(payload, dict) else {}
    for attempt in range(retries):
        try:
            response = requests.get(jira_search_url, headers=headers, auth=auth, params=params, timeout=300)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            backoff = delay * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(f"Retrying API call to {jira_search_url} after {backoff:.2f} seconds. Attempt {attempt + 1}/{retries}. Error: {e}")
            time.sleep(backoff)
    logging.error(f"Failed to fetch issues from {jira_search_url} after multiple retries.")
    return None


def run_merge_query(client, dataset_id, table_id, temp_table_id):
    """Execute MERGE query to upsert changelog data."""
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


def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, level, message, FunctionName=None, BatchID=None, Details=None):
    """Buffer a log entry to be flushed to BigQuery."""
    log_entry = {
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
    """Flush all buffered logs to BigQuery PipelineRuns table."""
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
    """Sync Jira changelog/transition history to BigQuery."""
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
    search_api_endpoint = f"{jira_base_url}/rest/api/3/search/jql"
    rows_inserted = 0

    while start_at < total_issues:
        headers = {"Accept": "application/json"}
        auth = (username, api_token)
        params = {"jql": jql_query, "startAt": start_at, "maxResults": max_results, "fields": "key"}

        logging.info(f"Fetching issues from Jira: {search_api_endpoint} with JQL, startAt {start_at}, maxResults {max_results}")
        try:
            data = fetch_issues_with_retry(search_api_endpoint, headers, auth, params)
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

            if len(rows_to_insert) >= batch_size:
                if insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                    rows_inserted += len(rows_to_insert)
                else:
                    logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                    delete_temp_table(client, dataset_id, temp_table_id)
                    return False
                rows_to_insert = []

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
        start_at += max_results
        time.sleep(1)

    if rows_inserted > 0:
        run_merge_query(client, dataset_id, table_id, temp_table_id)
    delete_temp_table(client, dataset_id, temp_table_id)
    return int(rows_inserted)


def main():
    """Main pipeline execution."""
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration. Exiting.")
        return

    jira_base_url = 'https://consoleconnect.atlassian.net'
    base_default = (
        '('
        'project = "GS&O Data Analytics" OR '
        'project = "Customer Success Management" OR '
        'project = "GS&O Tool Automation" OR '
        'project = "GS&O Knowledge Consolidation" OR '
        'project = TAC OR '
        'project = "VOICE - CE" OR '
        'project = "IOT CE" OR '
        'project = "Console Application Support" OR '
        'project = "Console Connect Provisioning" OR '
        'project = "Global Service Delivery Team" OR '
        'project = "Transmission TX-CE" OR '
        'project = "Mobility SMS - CE" OR '
        'project = "Managed Security Services" OR '
        'project = Sherbet OR '
        'project = "Google Contact Center AI Solution" OR '
        'project = "QMS Documentation" OR '
        'project = "Operational Case Reviews" OR '
        'project = "IT Helpdesk" OR '
        'project = "GS&O Strategic Initiatives" '
        ')'
    )
    base_jql = load_base_jql(default_text=base_default)
    logging.info(f"Resolved base_jql for hourly changelog job: {base_jql}")
    if not base_jql:
        return
    jql_query = build_jql(base_jql, "status CHANGED DURING (-1h, now())", joiner='AND')
    logging.info(f"Final jql_query for changelog: {jql_query}")

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
        return

    try:
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")
        rows_merged = sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client)
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        if rows_merged is None or (isinstance(rows_merged, int) and rows_merged < 0):
            logging.error("Failed to sync transition history to BigQuery.")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message="Failed to sync transition history to BigQuery", status="ERROR", duration_seconds=duration_seconds)
        else:
            logging.info(f"Sync complete. Rows merged: {int(rows_merged)}")
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline finished", status="SUCCESS", window_start=jql_window_start, window_end=jql_window_end, rows_merged=int(rows_merged), duration_seconds=duration_seconds)
    except Exception as e:
        logging.exception(f"Pipeline run failed: {e}")
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message=f"Exception: {e}", status="ERROR", error_code=getattr(e, "code", None), duration_seconds=duration_seconds)

    flush_logs_to_bigquery(client, dataset_id, log_table_id)


if __name__ == "__main__":
    main()
