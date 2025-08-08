import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime, timedelta
import time
import os
from concurrent.futures import ThreadPoolExecutor
import random
import uuid

# --- Logging Buffer for BigQuery Logs ---
LOG_BUFFER = []

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEBUG = False  # Set to True to enable detailed logging

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token and email.")
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

def wait_for_table(client, dataset_id, table_id, retries=5, delay=5):
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
            # Use data=payload (JSON string) for compatibility with Jira API, as in the working comments sync script
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
    if not LOG_BUFFER:
        return
    # Use run_id from the first log entry (all logs in a run share the same run_id)
    run_id = LOG_BUFFER[0]["RunID"] if LOG_BUFFER and "RunID" in LOG_BUFFER[0] else str(uuid.uuid4())
    temp_log_table = f"PipelineLogs_temp_{run_id.replace('-', '')}"
    log_schema = [
        bigquery.SchemaField("PipelineName", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("RunID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("LogLevel", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Message", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("FunctionName", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("BatchID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Details", "STRING", mode="NULLABLE"),
    ]
    if not create_or_replace_temp_table(client, dataset_id, temp_log_table, log_schema):
        logging.error("Setup failed: Could not create temp logs table.")
        return
    if not wait_for_table(client, dataset_id, temp_log_table, retries=5, delay=5):
        logging.error("Setup failed: Temp logs table not available.")
        return
    if not insert_rows_with_retry(client, dataset_id, temp_log_table, LOG_BUFFER, retries=5, delay=5):
        logging.error("Failed to insert log entries into temp logs table after retries.")
        return
    merge_query = f"""
        MERGE `{client.project}.{dataset_id}.PipelineLogs` T
        USING (
            SELECT DISTINCT * FROM `{client.project}.{dataset_id}.{temp_log_table}`
        ) S
        ON T.RunID = S.RunID AND T.Message = S.Message
        WHEN MATCHED THEN
            UPDATE SET
                T.PipelineName = S.PipelineName,
                T.LogLevel = S.LogLevel,
                T.FunctionName = S.FunctionName,
                T.BatchID = S.BatchID,
                T.Details = S.Details
        WHEN NOT MATCHED THEN
            INSERT (PipelineName, RunID, LogLevel, Message, FunctionName, BatchID, Details)
            VALUES (S.PipelineName, S.RunID, S.LogLevel, S.Message, S.FunctionName, S.BatchID, S.Details)
    """
    client.query(merge_query).result()
    client.delete_table(f"{dataset_id}.{temp_log_table}")
    logging.info("All log entries successfully merged into BigQuery logs table.")

def sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
    temp_table_id = f"{table_id}_temp"
    # Use a unique temp table name per run to avoid collisions
    run_id = datetime.utcnow().strftime('%Y%m%d%H%M%S') + '_' + str(uuid.uuid4())[:8]
    temp_table_id = f"{table_id}_temp_{run_id}"

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

    # --- Automated Time Partitioning Logic ---
    # Use a BigQuery table to track progress of time windows processed
    progress_table = f"{table_id}_progress"
    progress_schema = [
        bigquery.SchemaField("WindowStart", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("WindowEnd", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),  # e.g. 'complete', 'in_progress', 'failed'
        bigquery.SchemaField("LastRun", "TIMESTAMP", mode="NULLABLE"),
    ]
    # Ensure progress table exists, but do NOT recreate or replace it
    if not table_exists(client, dataset_id, progress_table):
        try:
            client.create_table(bigquery.Table(f"{client.project}.{dataset_id}.{progress_table}", schema=progress_schema))
            logging.info(f"Progress table '{client.project}.{dataset_id}.{progress_table}' created.")
        except Exception as e:
            logging.error(f"Error creating progress table: {e}")

    # Define window size (e.g., 7 days for full history, or 1 day for incremental)
    window_days = 1
    # Restrict to only process data from 2024 onwards
    min_ts = datetime(2024, 7, 1)

    # Find the latest transition timestamp in Jira (for upper bound)
    now = datetime.utcnow()


    # Find the earliest window with status not 'complete'
    progress_query = f"SELECT WindowStart, WindowEnd FROM `{client.project}.{dataset_id}.{progress_table}` WHERE Status != 'complete' ORDER BY WindowStart ASC LIMIT 1"
    window_start = None
    window_end = None
    try:
        result = client.query(progress_query).result()
        for row in result:
            window_start = row.WindowStart
            window_end = row.WindowEnd
            break
    except Exception as e:
        logging.warning(f"Could not query progress table: {e}")

    if window_start and window_end:
        # There is an incomplete window, process it
        window_end_candidate = window_end
    else:
        # All windows complete or no windows, advance to next window
        # Find the latest window
        latest_query = f"SELECT WindowEnd FROM `{client.project}.{dataset_id}.{progress_table}` ORDER BY WindowEnd DESC LIMIT 1"
        latest_end = None
        try:
            result = client.query(latest_query).result()
            for row in result:
                latest_end = row.WindowEnd
                break
        except Exception as e:
            logging.warning(f"Could not query for latest window: {e}")
        if latest_end:
            window_start = latest_end
        else:
            window_start = min_ts
        window_end_candidate = window_start + timedelta(days=window_days)

    # Ensure both window_end_candidate and now are offset-naive for comparison
    if hasattr(window_end_candidate, 'tzinfo') and window_end_candidate.tzinfo is not None and window_end_candidate.tzinfo.utcoffset(window_end_candidate) is not None:
        window_end_candidate_naive = window_end_candidate.replace(tzinfo=None)
    else:
        window_end_candidate_naive = window_end_candidate

    if now.tzinfo is not None and now.tzinfo.utcoffset(now) is not None:
        now_naive = now.replace(tzinfo=None)
    else:
        now_naive = now

    window_end = min(window_end_candidate_naive, now_naive)

    # Mark this window as in_progress using BigQuery-compatible MERGE
    try:
        merge_query = f'''
            MERGE `{client.project}.{dataset_id}.{progress_table}` T
            USING (SELECT TIMESTAMP('{window_start}') AS WindowStart, TIMESTAMP('{window_end}') AS WindowEnd) S
            ON T.WindowStart = S.WindowStart AND T.WindowEnd = S.WindowEnd
            WHEN MATCHED THEN
              UPDATE SET Status = 'in_progress', LastRun = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN
              INSERT (WindowStart, WindowEnd, Status, LastRun)
              VALUES (S.WindowStart, S.WindowEnd, 'in_progress', CURRENT_TIMESTAMP())
        '''
        client.query(merge_query).result()
        logging.info(f"Progress table updated: window {window_start} to {window_end} marked as in_progress.")
    except Exception as e:
        logging.warning(f"Could not update progress table: {e}")

    # Build JQL for this window (use updated >= ... AND updated < ... for API compatibility)
    window_jql = (
        f"({jql_query}) AND updated >= '{window_start.strftime('%Y/%m/%d %H:%M')}' "
        f"AND updated < '{window_end.strftime('%Y/%m/%d %H:%M')}'"
    )

    total_issues = float('inf')
    start_at = 0
    max_results = 100
    issues_processed = 0
    batch_size = 1000
    search_api_endpoint = f"{jira_base_url}/rest/api/2/search"
    rows_inserted = False

    while start_at < total_issues:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (username, api_token)
        payload = json.dumps({"jql": window_jql, "startAt": start_at, "maxResults": max_results, "fields": ["key"]})

        logging.info(f"Fetching issues from Jira: {search_api_endpoint} with JQL window {window_start} to {window_end}, startAt {start_at}, maxResults {max_results}")
        try:
            data = fetch_issues_with_retry(search_api_endpoint, headers, auth, payload)
            if data is None:
                logging.error(f"Repeated failures in fetching issues. Merging and exiting.")
                if rows_inserted:
                    run_merge_query(client, dataset_id, table_id, temp_table_id)
                delete_temp_table(client, dataset_id, temp_table_id)
                # Mark window as failed
                client.query(f"UPDATE `{client.project}.{dataset_id}.{progress_table}` SET Status='failed', LastRun=CURRENT_TIMESTAMP() WHERE WindowStart=TIMESTAMP('{window_start}') AND WindowEnd=TIMESTAMP('{window_end}')").result()
                return False
        except Exception as e:
            logging.error(f"Unexpected error during issue fetch: {e}")
            start_at += max_results
            continue

        issues = data.get('issues', [])
        total_issues = data.get('total', 0)

        if not issues:
            if start_at == 0:
                logging.info(f"No issues found for JQL window: {window_jql}")
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
                try:
                    created_dt = datetime.strptime(created_timestamp, '%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    logging.warning(f"Could not parse created_timestamp {created_timestamp} for history {history_id}: {e}")
                    continue
                # Ensure all datetimes are offset-naive for comparison
                ws = window_start.replace(tzinfo=None) if hasattr(window_start, 'tzinfo') and window_start.tzinfo is not None else window_start
                we = window_end.replace(tzinfo=None) if hasattr(window_end, 'tzinfo') and window_end.tzinfo is not None else window_end
                cd = created_dt.replace(tzinfo=None) if hasattr(created_dt, 'tzinfo') and created_dt.tzinfo is not None else created_dt
                if not (ws <= cd < we):
                    continue  # Skip transitions outside the window
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
                    rows_inserted = True
                else:
                    logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                    if rows_inserted:
                        # Merge whatever is in temp table before exit
                        run_merge_query(client, dataset_id, table_id, temp_table_id)
                    delete_temp_table(client, dataset_id, temp_table_id)
                    # Mark window as failed
                    client.query(f"UPDATE `{client.project}.{dataset_id}.{progress_table}` SET Status='failed', LastRun=CURRENT_TIMESTAMP() WHERE WindowStart=TIMESTAMP('{window_start}') AND WindowEnd=TIMESTAMP('{window_end}')").result()
                    return False
                rows_to_insert = []

        # Insert any remaining rows after processing all issues on the page
        if rows_to_insert:
            if insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                rows_inserted = True
            else:
                logging.error(f"Failed to insert remaining rows into temp table. Stopping processing.")
                if rows_inserted:
                    # Merge whatever is in temp table before exit
                    run_merge_query(client, dataset_id, table_id, temp_table_id)
                delete_temp_table(client, dataset_id, temp_table_id)
                # Mark window as failed
                client.query(f"UPDATE `{client.project}.{dataset_id}.{progress_table}` SET Status='failed', LastRun=CURRENT_TIMESTAMP() WHERE WindowStart=TIMESTAMP('{window_start}') AND WindowEnd=TIMESTAMP('{window_end}')").result()
                return False

        issues_processed += len(issues)
        logging.info(f"Processed details for {len(issues)} issues. Total issues processed so far: {issues_processed} out of {total_issues}")
        remaining_issues = total_issues - issues_processed
        logging.info(f"Remaining issues to process: {remaining_issues}")
        start_at += max_results  # Advance to next page
        time.sleep(1)


    # Merge temp table into final table (upsert logic)
    if rows_inserted:
        run_merge_query(client, dataset_id, table_id, temp_table_id)
    delete_temp_table(client, dataset_id, temp_table_id)

    # Mark only the exact matching window as complete in the progress table (robust to microsecond differences)
    try:
        # Round timestamps to the nearest second for comparison
        window_start_rounded = window_start.replace(microsecond=0)
        window_end_rounded = window_end.replace(microsecond=0)
        update_query = f"""
            UPDATE `{client.project}.{dataset_id}.{progress_table}`
            SET Status='complete', LastRun=CURRENT_TIMESTAMP()
            WHERE TIMESTAMP_TRUNC(WindowStart, SECOND) = TIMESTAMP('{window_start_rounded}')
              AND TIMESTAMP_TRUNC(WindowEnd, SECOND) = TIMESTAMP('{window_end_rounded}')
              AND Status != 'complete'
        """
        result = client.query(update_query).result()
        updated_count = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else None
        if updated_count and updated_count > 0:
            logging.info(f"Marked window {window_start_rounded} to {window_end_rounded} as complete.")
        else:
            logging.warning(f"No window was marked as complete. Check timestamp precision and progress table.")
    except Exception as e:
        logging.warning(f"Could not mark window as complete in progress table: {e}")

    return True


def main():
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration. Exiting.")
        return

    jira_base_url = 'https://consoleconnect.atlassian.net'
    jql_query = (
        '('
        'project = "GS&O Data Analytics" OR '
        'project = "GS&O Tool Automation" OR '
        'project = "GS&O Knowledge Consolidation" OR '
        'project = "Google Contact Center AI Solution" OR '
        'project = TAC OR '
        'project = CCAS OR '
        'project = VOICECE OR '
        'project = IOTCE OR '
        'project = TXCE OR '
        'project = SMSCE OR '
        'project = MSS OR '
        'project = "Console Application Support" OR '
        'project = "Console Connect Provisioning" OR '
        'project = "Global Service Delivery Team" OR '
        'project = "Transmission TX-CE" OR '
        'project = "Mobility SMS - CE" OR '
        'project = "Managed Security Services"'
        ')'
    )

    username = 'jjkli@consoleconnect.com'
    logging.info(f"Using Jira username: {username}")

    api_token = config.get('jira_api_token')
    if not api_token:
        logging.error("Jira API token not found in config.json. Exiting.")
        return

    dataset_id = 'GSO'
    table_id = 'JiraChangelog'
    log_table_id = 'PipelineLogs'
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
        if sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
            logging.info("Successfully synced transitions history to BigQuery.")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Successfully synced transitions history to BigQuery", FunctionName="main")
        else:
            logging.error("Failed to sync transition history to BigQuery.")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", "Failed to sync transition history to BigQuery", FunctionName="main")
    except Exception as e:
        logging.exception(f"Pipeline run failed: {e}")
        log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Pipeline run failed: {e}", FunctionName="main", Details=str(e))

    # Log pipeline end
    log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline finished", FunctionName="main")

    # At the end, flush all logs to BigQuery in a batch
    flush_logs_to_bigquery(client, dataset_id, log_table_id)

if __name__ == "__main__":
    main()