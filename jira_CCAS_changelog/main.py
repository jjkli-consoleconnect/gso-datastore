import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os # This import is present but os module is not used. Can be removed if not needed later.
from concurrent.futures import ThreadPoolExecutor
import random

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
        backoff = delay * (2 ** attempt) + random.uniform(0, 1)
        logging.info(f"Retrying insert rows into table '{client.project}.{dataset_id}.{table_id}' after {backoff:.2f} seconds. Attempt {attempt + 1}/{retries}")
        time.sleep(backoff)
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

def sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
    temp_table_id = f"{table_id}_temp"

    schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("History_ID", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Transition_Timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("Transitioned_From", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_To", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Display_Name", "STRING", mode="NULLABLE"),
    ]

    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, schema):
        logging.error("Failed to create or replace temporary table.")
        return False

    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error(f"Temporary table '{temp_table_id}' is not available.")
        return False

    total_issues = float('inf')
    start_at = 0
    max_results = 75
    issues_processed = 0
    batch_size = 500 # BQ insert batch size

    # Construct the full search URL once
    # Jira Cloud typically uses /rest/api/2/ or /rest/api/3/. /rest/api/latest/ resolves to one of these.
    # Using /rest/api/2/ as it was in the original script and is widely compatible.
    search_api_endpoint = f"{jira_base_url}/rest/api/2/search"

    while start_at < total_issues:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (username, api_token) # For Jira Cloud, username is typically the email address
        payload = json.dumps({"jql": jql_query, "startAt": start_at, "maxResults": max_results, "fields": ["key"]}) # Only fetch 'key' initially

        logging.info(f"Fetching issues from Jira: {search_api_endpoint} with JQL starting at {start_at}, maxResults {max_results}")
        try:
            data = fetch_issues_with_retry(search_api_endpoint, headers, auth, payload)
            if data is None:
                logging.error(f"Skipping batch starting at {start_at} due to repeated failures in fetching issues.")
                start_at += max_results # Ensure loop progresses
                continue
        except Exception as e: # Catching generic Exception here is broad, but mirrors original
            logging.error(f"Unexpected error during issue fetch: {e}")
            start_at += max_results # Ensure loop progresses
            continue

        issues = data.get('issues', [])
        total_issues = data.get('total', 0) # Update total_issues from the first successful response

        if not issues:
            if start_at == 0: # No issues found at all
                logging.info(f"No issues found for JQL: {jql_query}")
            else:
                logging.info(f"No more issues found on page starting at {start_at}.")
            break # Exit loop if no issues are returned

        logging.info(f"Fetched {len(issues)} issues. Total according to Jira: {total_issues}. Current offset: {start_at}")

        rows_to_insert = []
        # Fetch histories in parallel for the current page of issues
        issue_histories = fetch_issue_histories_parallel(jira_base_url, issues, username, api_token)

        for issue_data in issues: # Renamed 'issue' to 'issue_data' to avoid conflict with 'issues' list
            issue_key = issue_data.get('key')
            if not issue_key:
                logging.warning(f"Issue missing key in search results. Data: {issue_data}. Skipping.")
                continue

            issue_history_detail = issue_histories.get(issue_key)

            if issue_history_detail is None:
                logging.warning(f"Could not retrieve history for issue {issue_key}. Skipping.")
                continue

            histories = issue_history_detail.get('changelog', {}).get('histories', [])

            for history_entry in histories: # Renamed 'history' to 'history_entry'
                history_id = history_entry.get('id')
                author = history_entry.get('author', {})
                created_timestamp = convert_timestamp(history_entry.get('created')) # Renamed 'created'

                if not created_timestamp:
                    logging.warning(f"Skipping history entry {history_id} for issue {issue_key} due to invalid creation timestamp.")
                    continue

                for item in history_entry.get('items', []):
                    if item.get('fieldId') == 'status' or item.get('field') == 'status': # Check both field and fieldId for status
                        rows_to_insert.append({
                            "Issue_Key": issue_key,
                            "History_ID": history_id,
                            "Transition_Timestamp": created_timestamp,
                            "Transitioned_From": item.get('fromString'),
                            "Transitioned_To": item.get('toString'),
                            "Transitioned_By_Account_ID": author.get('accountId'), # Account ID is preferred for Cloud
                            "Transitioned_By_Display_Name": author.get('displayName'),
                        })

            # Insert rows in batches to BigQuery temp table
            if len(rows_to_insert) >= batch_size:
                if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                    logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                    # Clean up temp table before exiting might be good here, or handle upstream.
                    delete_temp_table(client, dataset_id, temp_table_id)
                    return False
                rows_to_insert = []

        # Insert any remaining rows after processing all issues on the page
        if rows_to_insert:
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                logging.error(f"Failed to insert final batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                delete_temp_table(client, dataset_id, temp_table_id)
                return False
            rows_to_insert = [] # Clear it after successful insert

        start_at += max_results
        issues_processed += len(issues)
        logging.info(f"Processed details for {len(issues)} issues. Total issues processed so far: {issues_processed} out of {total_issues}")
        time.sleep(1) # Reduced sleep, rely more on retry backoff for rate limits. Original was 2s.

    # MERGE from temp table to final table
    # Ensure project ID is included in table references for clarity and cross-project queries
    merge_query = f"""
        MERGE `{client.project}.{dataset_id}.{table_id}` T
        USING `{client.project}.{dataset_id}.{temp_table_id}` S
        ON T.History_ID = S.History_ID AND T.Issue_Key = S.Issue_Key
        WHEN MATCHED THEN
            UPDATE SET
                T.Transition_Timestamp = S.Transition_Timestamp,
                T.Transitioned_From = S.Transitioned_From,
                T.Transitioned_To = S.Transitioned_To,
                T.Transitioned_By_Account_ID = S.Transitioned_By_Account_ID,
                T.Transitioned_By_Display_Name = S.Transitioned_By_Display_Name
        WHEN NOT MATCHED THEN
            INSERT (Issue_Key, History_ID, Transition_Timestamp, Transitioned_From, Transitioned_To, Transitioned_By_Account_ID, Transitioned_By_Display_Name)
            VALUES (S.Issue_Key, S.History_ID, S.Transition_Timestamp, S.Transitioned_From, S.Transitioned_To, S.Transitioned_By_Account_ID, S.Transitioned_By_Display_Name)
    """
    logging.info(f"Executing MERGE query into {client.project}.{dataset_id}.{table_id}")
    try:
        query_job = client.query(merge_query)
        query_job.result()  # Wait for the job to complete
        logging.info(f"Merge query executed successfully. {query_job.num_dml_affected_rows} rows affected.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        # Consider not deleting temp table on MERGE failure for debugging
        return False
    finally:
        # Delete the temporary table after merging or if merge fails but we want to clean up
        if not delete_temp_table(client, dataset_id, temp_table_id):
            logging.error(f"Failed to delete temporary table: {client.project}.{dataset_id}.{temp_table_id}")
            # This doesn't cause the main function to return False, which might be intended.
            # If deletion failure is critical, add 'return False' here.

    return True

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

    jira_base_url = 'https://consoleconnect.atlassian.net' # Base URL for Jira Cloud
    jql_query = 'project = "CCAS" AND updated >= endOfDay(-3) ORDER BY updated ASC'

    username = 'jjkli@consoleconnect.com'
    logging.info(f"Using Jira username: {username}")


    api_token = config.get('jira_api_token')
    if not api_token:
        logging.error("Jira API token not found in config.json. Exiting.")
        return

    dataset_id = 'JIRAProjects'  # Replace with your BigQuery dataset ID if different
    table_id = 'CCAS_changelog'  # Replace with your desired BigQuery table ID if different

    # Ensure GOOGLE_APPLICATION_CREDENTIALS environment variable is set,
    # or the script is running in an environment with appropriate service account permissions.
    try:
        client = bigquery.Client()
        logging.info(f"Successfully connected to BigQuery project: {client.project}")
    except Exception as e:
        logging.error(f"Failed to initialize BigQuery client: {e}")
        return

    if sync_transition_history_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
        logging.info("Successfully synced transitions history to BigQuery.")
    else:
        logging.error("Failed to sync transition history to BigQuery.")

if __name__ == "__main__":
    main()