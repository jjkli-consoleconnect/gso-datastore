import requests
import sys, pathlib
# Ensure repo root is on sys.path so service_account_env can be imported when running this script directly
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from service_account_env import ensure as _ensure_sa
_ensure_sa()
import json
from google.cloud import bigquery
import logging
from datetime import datetime, timedelta, timezone
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from bq_logger import log_to_bigquery
import uuid
from typing import Optional
from pipeline_runs_logger import log_pipeline_run

"""Logging configuration"""
# DEBUG flag and LOG_LEVEL override
DEBUG = str(os.environ.get('DEBUG', '')).lower() in ('1', 'true', 'yes')
_env_level = os.environ.get('LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO').upper()
_level = getattr(logging, _env_level, logging.INFO)

# Setup logging (allow LOG_LEVEL to override, default INFO; DEBUG -> DEBUG)
logging.basicConfig(level=_level, format='%(asctime)s - %(levelname)s - %(message)s')

# Quiet noisy third-party loggers when not in DEBUG/when level > INFO
if _level > logging.INFO:
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('google.cloud').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

# --- Logging Buffer for BigQuery Logs ---
LOG_BUFFER = []

logging.info("Script startup test log")

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        return None

def load_base_jql(default_text: Optional[str] = None) -> Optional[str]:
    """Use the embedded default JQL from the script only.

    This intentionally ignores any external files or environment-based JQL so the
    script behavior matches the Docker image which embeds the JQL.
    """
    if default_text:
        logging.info("Using embedded default base JQL from script.")
        return default_text.strip()
    logging.error("No embedded base JQL provided in the script.")
    return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            # Adjust format string to handle potential lack of milliseconds
            # Also, ensure timezone offset is handled correctly (e.g., '+0000' or 'Z')
            # Jira Cloud often returns 'Z' for UTC
            if timestamp.endswith('Z'):
                 return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%d %H:%M:%S')
            else: # Try with milliseconds and timezone offset
                 return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
            # Attempt to parse without milliseconds if the above fails
            try:
                if timestamp.endswith('Z'):
                     return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')
                else:
                     return datetime.strptime(timestamp.rsplit('.', 1)[0] + timestamp.rsplit('.', 1)[1][3:], '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e2:
                logging.warning(f"Could not parse timestamp after retry: {timestamp}, Error: {e2}")
                return None
    return None


def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        # Use standard SQL for CREATE OR REPLACE
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(f'`{f.name}` {f.field_type}' for f in schema)})"
        logging.debug(f"Executing query: {query}")
        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced.")
        return True
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")
        return False

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
        return True
    except Exception as e:
        # Handle case where table might not exist (e.g., script failed early)
        if 'Not found' in str(e):
             logging.warning(f"Temporary table '{dataset_id}.{table_id}' not found during deletion attempt, likely already gone or never created.")
             return True # Treat as successful deletion if not found
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception as e:
        # BigQuery client raises a NotFound exception if the table doesn't exist
        if 'Not found' in str(e):
            return False
        logging.exception(f"Error checking existence of table '{dataset_id}.{table_id}': {e}")
        return False

def wait_for_table(client, dataset_id, table_id, retries=10, delay=5):
    for attempt in range(retries):
        if table_exists(client, dataset_id, table_id):
            logging.info(f"Table '{dataset_id}.{table_id}' is now available.")
            return True
        logging.debug(f"Waiting for table '{dataset_id}.{table_id}'. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    logging.error(f"Table '{dataset_id}.{table_id}' is not available after {retries} attempts.")
    return False

def insert_rows_with_retry(client, dataset_id, table_id, rows, schema, retries=5, delay=5):
    for attempt in range(retries):
        try:
            # Use the table reference directly for insertion
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into '{dataset_id}.{table_id}'.")
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            # Explicitly check for 'Not found' error which indicates the table is missing/truncated
            if "Not found" in str(e) or "Table is truncated" in str(e):
                 logging.warning(f"Table '{dataset_id}.{table_id}' not found or truncated during insert. Recreating...")
                 if create_or_replace_temp_table(client, dataset_id, table_id, schema) and wait_for_table(client, dataset_id, table_id):
                     logging.info("Table recreated successfully, retrying insert.")
                     continue # Retry the insert immediately after recreation
                 else:
                     logging.error("Failed to recreate table or wait for it to become available. Cannot retry insert.")
                     return False # Cannot proceed if recreation fails
            else:
                logging.exception(f"Error inserting rows into BigQuery (Attempt {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            logging.info(f"Retrying insert rows into '{dataset_id}.{table_id}'. Attempt {attempt + 2}/{retries}")
            time.sleep(delay)
        else:
            logging.error(f"Failed to insert rows after {retries} attempts.")
            return False
    return False # Should be unreachable if retries Exhausted, but good practice

# Use /rest/api/2 for comments as it's generally compatible
def fetch_comments_for_issue(jira_base_url, issue_key, username, api_token, max_results=75):
    all_comments = []
    start_at = 0

    while True:
        # Construct the full URL using the base URL and the /rest/api/2 path
        url = f"{jira_base_url}/rest/api/2/issue/{issue_key}/comment"
        headers = {"Accept": "application/json"}
        # Basic Auth with username and API token
        auth = (username, api_token)
        params = {"startAt": start_at, "maxResults": max_results}

        logging.debug(f"Fetching comments for {issue_key} starting at {start_at}")

        try:
            # Add a timeout for the request
            response = requests.get(url, headers=headers, auth=auth, params=params, timeout=120)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            data = response.json()
            comments = data.get('comments', [])
            all_comments.extend(comments)

            total_comments = data.get('total', 0)
            if start_at + len(comments) >= total_comments: # Check if we got all comments on this page or exceeded total
                 break # Exit the loop if all comments are fetched

            start_at += len(comments) # Use actual number of comments returned in case max_results is ignored/capped


        except requests.RequestException as e:
            # Log specific error details, including response text if available
            error_message = f"Error fetching comments for issue {issue_key}: {e}"
            if e.response is not None:
                 error_message += f", Status Code: {e.response.status_code}, Response Text: {e.response.text}"
            logging.error(error_message)
            return None # Return None to indicate failure for this issue

        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for comments of issue {issue_key}: {e}")
            return None # Return None to indicate failure

    logging.debug(f"Fetched {len(all_comments)} comments for issue {issue_key}")
    return all_comments

def fetch_comments_batch(jira_base_url, issue_keys, username, api_token, max_results=75):
    # Pass the base URL to the worker function
    def fetch_single_issue(key):
        return key, fetch_comments_for_issue(jira_base_url, key, username, api_token, max_results)

    results = {}
    # Use a reasonable number of workers, adjust based on your environment and Jira Cloud rate limits
    MAX_CONCURRENT_COMMENT_FETCHES = 16 # Increased from 8, can be tuned
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COMMENT_FETCHES) as executor:
        # Use a dictionary comprehension for cleaner submission
        future_to_key = {executor.submit(fetch_single_issue, key): key for key in issue_keys}
        
        for future in as_completed(future_to_key):
            issue_key = future_to_key[future]
            try:
                key, comments = future.result()
                results[key] = comments
                # Add a small delay between requests to potentially help with rate limits
                time.sleep(0.1) 
            except Exception as exc:
                logging.error(f'{issue_key} generated an exception: {exc}')
                results[issue_key] = None # Indicate failure for this specific issue

    return results

def generate_rows(issues, jira_base_url, username, api_token):
    # Ensure issue_keys only contains valid keys
    issue_keys = [issue.get('key') for issue in issues if issue and issue.get('key')]
    if not issue_keys:
        logging.warning("No valid issue keys provided to generate_rows.")
        return # Generator yields nothing

    # Pass the base URL to the batch fetch function
    comments_batch = fetch_comments_batch(jira_base_url, issue_keys, username, api_token)

    utc_now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    for issue_key in issue_keys:
        comments = comments_batch.get(issue_key)
        if comments is None:
            continue
        if not comments:
            continue
        for comment in comments:
            try:
                comment_id = comment.get('id')
                if not comment_id:
                    continue
                author_info = comment.get('author', {})
                visibility_info = comment.get('visibility', {})
                yield {
                    "Issue_Key": issue_key,
                    "Comment_ID": comment_id,
                    "Author_Account_ID": author_info.get('accountId'),
                    "Author_Display_Name": author_info.get('displayName'),
                    "Created": convert_timestamp(comment.get('created')),
                    "Updated": convert_timestamp(comment.get('updated')),
                    "Body": comment.get('body'),
                    "Visibility_Type": visibility_info.get('type'),
                    "Visibility_Value": visibility_info.get('value'),
                    "SyncTime": utc_now,
                    "InsertedAt": utc_now,
                }
            except Exception as e:
                logging.exception(f"Error processing comment {comment.get('id')} for issue {issue_key}: {e}")


# Pass the base URL and the new JQL query
def sync_comments_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
    temp_table_id = 'JiraComments_temp'
    schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Comment_ID", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Author_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Author_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Body", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Value", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("InsertedAt", "TIMESTAMP", mode="NULLABLE"),
    ]

    temp_table_created = create_or_replace_temp_table(client, dataset_id, temp_table_id, schema)
    if not temp_table_created:
        logging.error("Setup failed: Could not create temp table. Falling back to local JSON output to avoid data loss.")
        # Ensure output dir exists
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
        os.makedirs(out_dir, exist_ok=True)
        local_rows = []
        # We'll still fetch data and append to local_rows, then write to file at the end.
        fallback_to_local = True
    else:
        fallback_to_local = False
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error("Setup failed: Temp table not available.")
            return -1

    # --- Jira Search and Data Extraction ---
    total_issues = float('inf')
    start_at = 0
    max_results = 100 # Max results for JQL search, can be up to 100 in Jira Cloud
    issues_processed = 0
    # Batch size for inserting rows into BigQuery - keep it reasonable
    batch_size = 1000 
    total_rows_inserted_to_temp = 0

    # Construct the full search URL using the base URL and the /rest/api/2 path
    # Although user mentioned '/latest', /rest/api/2/search is also valid and consistent
    # with the comments endpoint path used in the script.
    search_url = f"{jira_base_url}/rest/api/2/search" 
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)

    logging.info(f"Starting Jira search from {search_url}")

    while start_at < total_issues:
        # The payload now includes the direct 'jql' string
        payload = json.dumps({
            "jql": jql_query,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["key"] # Only need the issue key for fetching comments
        })

        logging.info(f"Fetching issues with JQL, startAt: {start_at}, maxResults: {max_results}")

        # --- Jira Search API Call with Retries ---
        response = None # Define response before the loop
        for attempt in range(5): # Increased retries for network issues
            try:
                # Add a generous timeout for the search request as it might be slow
                response = requests.post(search_url, headers=headers, auth=auth, data=payload, timeout=300) 
                response.raise_for_status()
                break # Success, exit retry loop
            except requests.exceptions.Timeout:
                 logging.warning(f"Search request timed out on attempt {attempt + 1}/5. Retrying...")
                 time.sleep(15) # Wait longer on timeout
            except requests.RequestException as e:
                error_message = f"Error searching issues on attempt {attempt + 1}/5: {e}"
                if e.response is not None:
                    error_message += f", Status Code: {e.response.status_code}, Response Text: {e.response.text}"
                    # Handle specific Jira Cloud rate limiting (429)
                    if e.response.status_code == 429:
                         retry_after = e.response.headers.get('Retry-After', 30) # Default 30 seconds
                         logging.warning(f"Rate limited (429). Retrying after {retry_after} seconds...")
                         time.sleep(int(retry_after))
                         continue # Skip sleep below, retry immediately after waiting
                logging.error(error_message)

                if attempt < 4:
                    logging.info(f"Retrying Jira search in 10 seconds...")
                    time.sleep(10)
                else:
                    logging.error("Failed to search issues after multiple attempts.")
                    delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                    return -1 # Give up after retries

        if response is None: # If loop finished without a successful response
            logging.error("Jira search failed after multiple retries.")
            # Merge temp table into final table before exit
            logging.info(f"Starting merge operation from '{dataset_id}.{temp_table_id}' to '{dataset_id}.{table_id}'...")
            merge_query = f"""
                MERGE `{dataset_id}.{table_id}` T
                USING (
                    SELECT DISTINCT
                        Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body,
                        Visibility_Type, Visibility_Value, SyncTime, InsertedAt
                    FROM `{dataset_id}.{temp_table_id}`
                ) S
                ON T.Comment_ID = S.Comment_ID AND T.Updated = S.Updated
                WHEN MATCHED THEN
                    UPDATE SET
                        T.Issue_Key = S.Issue_Key,
                        T.Author_Account_ID = S.Author_Account_ID,
                        T.Author_Display_Name = S.Author_Display_Name,
                        T.Created = S.Created,
                        T.Updated = S.Updated,
                        T.Body = S.Body,
                        T.Visibility_Type = S.Visibility_Type,
                        T.Visibility_Value = S.Visibility_Value,
                        T.SyncTime = S.SyncTime,
                        T.InsertedAt = S.InsertedAt
                WHEN NOT MATCHED THEN
                    INSERT (Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body, Visibility_Type, Visibility_Value, SyncTime, InsertedAt)
                    VALUES (S.Issue_Key, S.Comment_ID, S.Author_Account_ID, S.Author_Display_Name, S.Created, S.Updated, S.Body, S.Visibility_Type, S.Visibility_Value, S.SyncTime, S.InsertedAt)
            """
            try:
                query_job = client.query(merge_query)
                query_job.result()
                logging.info("Data merged successfully into final table.")
            except Exception as e:
                logging.exception(f"Error running merge query: {e}")
            delete_temp_table(client, dataset_id, temp_table_id)
            # No window to mark as failed; skip progress table update
            return -1

        # --- Process Search Results ---
        try:
            data = response.json()
            issues = data.get('issues', [])
            total_issues = data.get('total', 0) # Get the *total* number of issues matching the JQL

            if not issues:
                logging.info(f"No issues found on this page (startAt: {start_at}). Total issues reported: {total_issues}.")
                if start_at == 0 and total_issues > 0:
                    # This might happen if maxResults is too large or pagination is odd
                    logging.warning("Got 0 issues on first page but total > 0. Check maxResults or JQL.")
                break # No more issues to process

            logging.info(f"Fetched {len(issues)} issues (startAt: {start_at}) out of total {total_issues}")

            rows_to_insert = []
            # Pass the base URL to generate_rows (no window filtering)
            for row in generate_rows(issues, jira_base_url, username, api_token):
                rows_to_insert.append(row)
                if len(rows_to_insert) >= batch_size:
                    if fallback_to_local:
                        local_rows.extend(rows_to_insert)
                    else:
                        if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, schema):
                            logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                            delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                            return -1
                        total_rows_inserted_to_temp += len(rows_to_insert)
                    rows_to_insert = []

            # Insert any remaining rows in the last batch
            if rows_to_insert:
                if fallback_to_local:
                    local_rows.extend(rows_to_insert)
                else:
                    if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, schema):
                        logging.error(f"Failed to insert remaining {len(rows_to_insert)} rows into temp table. Stopping processing.")
                        delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                        return -1
                    total_rows_inserted_to_temp += len(rows_to_insert)


            start_at += len(issues) # Increment start_at by the number of issues *actually* returned
            issues_processed += len(issues)
            logging.info(f"Finished processing {len(issues)} issues from this page. Total issues processed so far: {issues_processed}/{total_issues}")

            # Optional: Add a short delay between search pages to be nice to Jira API
            time.sleep(1)

        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for search issues: {e}. Response text: {response.text if response else 'N/A'}")
            delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
            return -1
        except Exception as e:
            logging.exception(f"An unexpected error occurred during issue processing: {e}")
            delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
            return -1


    logging.info(f"Finished fetching and inserting data into temporary table '{temp_table_id}'. Total rows inserted: {total_rows_inserted_to_temp}")
    if fallback_to_local:
        # Write local_rows to timestamped JSON file
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        out_path = os.path.join(out_dir, f'jira_comments_{ts}.json')
        try:
            with open(out_path, 'w', encoding='utf-8') as out_f:
                json.dump(local_rows, out_f, ensure_ascii=False, indent=2)
            logging.info(f'Wrote {len(local_rows)} rows to local fallback file: {out_path}')
        except Exception as e:
            logging.exception(f'Failed to write local fallback file: {e}')
        # Skip merge and deletion since we never created temp table
        return len(local_rows)

    # --- Merge Data into Final Table ---
    logging.info(f"Starting merge operation from '{dataset_id}.{temp_table_id}' to '{dataset_id}.{table_id}'...")
    merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING (
            SELECT DISTINCT
                Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body,
                Visibility_Type, Visibility_Value, SyncTime, InsertedAt
            FROM `{dataset_id}.{temp_table_id}`
        ) S
        ON T.Comment_ID = S.Comment_ID AND T.Updated = S.Updated
        WHEN MATCHED THEN
            UPDATE SET
                T.Issue_Key = S.Issue_Key,
                T.Author_Account_ID = S.Author_Account_ID,
                T.Author_Display_Name = S.Author_Display_Name,
                T.Created = S.Created,
                T.Updated = S.Updated,
                T.Body = S.Body,
                T.Visibility_Type = S.Visibility_Type,
                T.Visibility_Value = S.Visibility_Value,
                T.SyncTime = S.SyncTime,
                T.InsertedAt = S.InsertedAt
        WHEN NOT MATCHED THEN
            INSERT (Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body, Visibility_Type, Visibility_Value, SyncTime, InsertedAt)
            VALUES (S.Issue_Key, S.Comment_ID, S.Author_Account_ID, S.Author_Display_Name, S.Created, S.Updated, S.Body, S.Visibility_Type, S.Visibility_Value, S.SyncTime, S.InsertedAt)
    """

    try:
        query_job = client.query(merge_query)
        query_job.result()
        logging.info("Data merged successfully into final table.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        return -1

    logging.info(f"Sync process completed for JQL: {jql_query}")

    # Drop temp table after merge
    delete_temp_table(client, dataset_id, temp_table_id)

    return int(total_rows_inserted_to_temp)

def wait_for_streaming_buffer_empty(client, project, dataset, table, max_wait=300, poll_interval=10):
    table_ref = f"{project}.{dataset}.{table}"
    waited = 0
    while waited < max_wait:
        table_obj = client.get_table(table_ref)
        if not hasattr(table_obj, 'streaming_buffer'):
            return True  
        buffer = table_obj.streaming_buffer
        if not buffer or buffer.estimated_rows == 0:
            return True
        logging.info(f"Waiting for streaming buffer to empty... ({buffer.estimated_rows} rows remaining)")
        time.sleep(poll_interval)
        waited += poll_interval
    logging.warning("Streaming buffer not empty after waiting. Proceeding anyway.")
    return False

CHECKPOINT_FILE = "jira_comments_checkpoint.json"





# Buffer log entries for batch BigQuery logging
def log_to_bigquery(client, dataset_id, table_id, pipeline_name, run_id, level, message, function_name=None, batch_id=None, details=None):
    log_entry = {
        "Timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "PipelineName": pipeline_name,
        "RunID": run_id,
        "LogLevel": level,
        "Message": message,
        "FunctionName": function_name,
        "BatchID": batch_id,
        "Details": details
    }
    LOG_BUFFER.append(log_entry)

# At the end of the pipeline, flush all logs to BigQuery in a batch
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

def main():
    # Removed troubleshooting debugging logs
    try:
        config = load_config()
        if config is None:
            return
        dataset_id = 'GSO'
        table_id = 'JiraComments'
        log_table_id = 'PipelineRuns'
        pipeline_name = "jira_comments"
        run_id = str(uuid.uuid4())
        jira_url = 'https://consoleconnect.atlassian.net'
        username = "jjkli@consoleconnect.com"
        api_token = config.get('jira_api_token')
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
            'project = "Customer Success Management" '
            ')'
        )
        base_jql = load_base_jql(default_text=base_default)
        if not base_jql:
            return
        jql_query = f"{base_jql} AND updated >= -1h"
        # Compute JQL window: last hour relative to run start
        run_started = datetime.now(timezone.utc)
        jql_window_start = run_started - timedelta(hours=1)
        jql_window_end = run_started
        try:
            client = bigquery.Client()
        except Exception as e:
            logging.exception(f"Failed to initialize BigQuery client: {e}. Ensure GCP credentials are set up correctly.")
            return
        log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline started", function_name="main")
        try:
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")
            rows_merged = sync_comments_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client)
            if rows_merged and rows_merged > -1:
                logging.info("Successfully synced comments to BigQuery.")
                log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Successfully synced comments to BigQuery", function_name="main")
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline finished", status="SUCCESS", window_start=jql_window_start, window_end=jql_window_end, rows_merged=int(rows_merged))
            else:
                logging.error("Failed to sync comments to BigQuery.")
                log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", "Failed to sync comments to BigQuery", function_name="main")
                log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message="Failed to sync comments to BigQuery", status="ERROR")
        except Exception as e:
            logging.exception(f"Pipeline run failed: {e}")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Pipeline run failed: {e}", function_name="main", details=str(e))
            log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="ERROR", message=f"Pipeline run failed: {e}", status="ERROR", error_code=getattr(e, "code", None))
        log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline finished", function_name="main")
        flush_logs_to_bigquery(client, dataset_id, log_table_id)
    except Exception as e:
        logging.exception(f"Unhandled exception in main(): {e}")

if __name__ == "__main__":
    main()