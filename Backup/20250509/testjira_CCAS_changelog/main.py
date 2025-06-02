import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os
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
        logging.error("config.json not found. Please create it with your Jira API token.")
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
        CREATE OR REPLACE TABLE `{dataset_id}.{table_id}`
        (
            {', '.join(f'{f.name} {f.field_type}' for f in schema)}
        )
        """
        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced.")
        return True
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")
        return False

def create_temp_table_if_not_exists(client, dataset_id, table_id, schema):
    if not table_exists(client, dataset_id, table_id):
        return create_or_replace_temp_table(client, dataset_id, table_id, schema)
    return True

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
        return True
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception as e:
        logging.error(f"Table '{dataset_id}.{table_id}' does not exist: {e}")
        return False

def wait_for_table(client, dataset_id, table_id, retries=10, delay=5):
    for attempt in range(retries):
        if table_exists(client, dataset_id, table_id):
            logging.info(f"Table '{dataset_id}.{table_id}' is now available.")
            return True
        logging.info(f"Waiting for table '{dataset_id}.{table_id}' to be available. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    logging.error(f"Table '{dataset_id}.{table_id}' is not available after {retries} attempts.")
    return False

def insert_rows_with_retry(client, dataset_id, table_id, rows, retries=5, delay=5):
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(client.dataset(dataset_id).table(table_id), rows)
            if not errors:
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            logging.exception(f"Error inserting rows into BigQuery: {e}")
        backoff = delay * (2 ** attempt) + random.uniform(0, 1)
        logging.info(f"Retrying insert rows into table '{dataset_id}.{table_id}' after {backoff:.2f} seconds. Attempt {attempt + 1}/{retries}")
        time.sleep(backoff)
    return False

def fetch_issue_history(jira_url, issue_key, username, api_token):
    """Fetches the history (including transitions) for a given issue."""
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
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_issue_history, jira_url, issue['key'], username, api_token): issue for issue in issues}
        results = {}
        for future in futures:
            issue_key = futures[future]['key']
            try:
                results[issue_key] = future.result()
            except Exception as e:
                logging.error(f"Error fetching history for issue {issue_key}: {e}")
        return results

import time
import random

def fetch_issues_with_retry(url, headers, auth, payload, retries=5, delay=5):
    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, auth=auth, data=payload, timeout=300)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            backoff = delay * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(f"Retrying API call after {backoff:.2f} seconds. Attempt {attempt + 1}/{retries}. Error: {e}")
            time.sleep(backoff)
    logging.error("Failed to fetch issues after multiple retries.")
    return None

def sync_transition_history_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client):
    # Setup
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

    total_issues = float('inf')  # Initialize to infinity, update on first response
    start_at = 0
    max_results = 75  # Optimal page size based on testing
    issues_processed = 0
    batch_size = 500

    while start_at < total_issues:
        url = f"{jira_url}/rest/api/2/search"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (username, api_token)
        payload = json.dumps({"jql": jql_query, "startAt": start_at, "maxResults": max_results})

        try:
            data = fetch_issues_with_retry(url, headers, auth, payload)
            if data is None:
                logging.error(f"Skipping batch starting at {start_at} due to repeated failures.")
                start_at += max_results
                continue
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            start_at += max_results
            continue

        issues = data.get('issues', [])
        total_issues = data.get('total', 0)

        if not issues:
            logging.info("No issues found on this page.")
            break

        rows_to_insert = []
        issue_histories = fetch_issue_histories_parallel(jira_url, issues, username, api_token)
        for issue in issues:
            issue_key = issue.get('key')
            if not issue_key:
                logging.warning(f"Issue missing key. Skipping.")
                continue

            issue_history = issue_histories.get(issue_key)

            if issue_history is None:
                logging.error(f"Could not retrieve history for issue {issue_key}. Skipping.")
                continue

            histories = issue_history.get('changelog', {}).get('histories', [])

            for history in histories:
                history_id = history.get('id')
                author = history.get('author', {})
                created = convert_timestamp(history.get('created'))

                for item in history.get('items', []):
                    if item.get('field') == 'status':
                        rows_to_insert.append({
                            "Issue_Key": issue_key,
                            "History_ID": history_id,
                            "Transition_Timestamp": created,
                            "Transitioned_From": item.get('fromString'),
                            "Transitioned_To": item.get('toString'),
                            "Transitioned_By_Account_ID": author.get('accountId'),
                            "Transitioned_By_Display_Name": author.get('displayName'),
                        })

                    if len(rows_to_insert) >= batch_size:
                        if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                            logging.error(f"Failed to insert batch of {batch_size} rows. Stopping processing.")
                            return False
                        rows_to_insert = []

        if rows_to_insert:
            insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert)

        start_at += max_results
        issues_processed += len(issues)
        logging.info(f"Processed {len(issues)} issues. Total issues processed: {issues_processed}")
        time.sleep(2)  # Add a 2-second delay between API calls

    #MERGE
    merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING `{dataset_id}.{temp_table_id}` S
        ON T.History_ID = S.History_ID and T.Issue_Key = S.Issue_Key
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

    try:
        client.query(merge_query).result()
        logging.info("Merge query executed successfully.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        return False

    # Delete the temporary table after merging
    if not delete_temp_table(client, dataset_id, temp_table_id):
        logging.error("Failed to delete temporary table.")
        return False

    return True

def run_query_with_retry(client, query, retries=5, delay=5):
    for attempt in range(retries):
        try:
            client.query(query).result()
            return True
        except Exception as e:
            logging.warning(f"Retrying query after {delay} seconds. Attempt {attempt + 1}/{retries}. Error: {e}")
            time.sleep(delay)
    logging.error("Failed to execute query after multiple retries.")
    return False

def main():
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration.")
        return None

    jira_url = 'https://jira.pccwglobal.com'  # Replace with your Jira base URL
    jql_query = 'filter=26447'  # Replace with your JQL query
    username = 'jjkli'  # Replace with your Jira username
    api_token = config.get('jira_api_token')  # Load from config file
    dataset_id = 'JIRA'  # Replace with your BigQuery dataset ID
    table_id = 'CCAS_changelog'  # Replace with your desired BigQuery table ID

    client = bigquery.Client()

    if sync_transition_history_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client):
        logging.info("Successfully synced transitions history to BigQuery.")
    else:
        logging.error("Failed to sync transition history to BigQuery.")

if __name__ == "__main__":
    main()