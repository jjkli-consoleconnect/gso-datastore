import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time

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
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.query(f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(f'{f.name} {f.field_type}' for f in schema)})").result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced.")
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")

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
        logging.info(f"Retrying insert rows into table '{dataset_id}.{table_id}'. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    return False

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://jira.pccwglobal.com/rest/api/2/search'
    jql_query = 'filter=25707'  # Updated filter ID
    username = 'jjkli'  #Your Jira username - REPLACE YOUR USERNAME
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 50
    CHUNK_SIZE = 1000  # Adjust this value based on expected data volume

    try:
        client = bigquery.Client()
        dataset_id = 'JIRA'
        table_id = 'project_CCAS'  # Correct target table name
        temp_table_id = 'project_CCAS_temp'  # Correct temporary table name

        schema = [
            bigquery.SchemaField("T", "STRING", mode="REQUIRED"),  # Use "T" for IssueType
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("TaskDefinition", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ConsoleService", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("PortProvStatus", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
        ]

        # Create or replace the temporary table
        create_or_replace_temp_table(client, dataset_id, temp_table_id, schema)

        # Wait for the temporary table to be available
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' does not exist after creation.")
            return

        # Check if the target table exists
        if not table_exists(client, dataset_id, table_id):
            logging.error(f"Target table '{dataset_id}.{table_id}' does not exist.")
            return

        rows_to_insert = []
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                         params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results},
                                         timeout=300)
                response.raise_for_status()
                data = response.json()
                logging.info(f"Fetched {len(data.get('issues', []))} issues from Jira.")

                issues = data.get('issues', [])
                if not issues:
                    break

                for issue in issues:
                    logging.info(f"Processing issue: {issue.get('key')}")
                    try:
                        fields = issue.get('fields', {})
                        if DEBUG:
                            logging.debug(f"Fields for issue {issue.get('key')}: {json.dumps(fields, indent=2)}")  # Log fields for debugging
                        rows_to_insert.append({
                            "T": fields.get('issuetype', {}).get('name') if fields.get('issuetype') else None,  # Use "T" for IssueType
                            "Key": issue.get('key'),
                            "Summary": fields.get('summary'),
                            "Status": fields.get('status', {}).get('name'),
                            "Created": convert_timestamp(fields.get('created')),
                            "Updated": convert_timestamp(fields.get('updated')),
                            "Resolved": convert_timestamp(fields.get('resolutiondate')),
                            "Assignee": fields.get('assignee', {}).get('displayName'),
                            "TaskDefinition": fields.get('customfield_17935', {}).get('value') if fields.get('customfield_17935') else None,
                            "ConsoleService": fields.get('customfield_17903', {}).get('value') if fields.get('customfield_17903') else None,
                            "PortProvStatus": fields.get('customfield_16605', {}).get('value') if fields.get('customfield_16605') else None,
                            "RemedyTicketNumber": fields.get('customfield_12204'),
                        })

                    except Exception as e:
                        logging.exception(f"Error processing issue {issue.get('key')}: {e}")

                start_at += max_results

                if len(rows_to_insert) >= CHUNK_SIZE:
                    logging.info(f"Inserting {len(rows_to_insert)} rows into BigQuery")
                    if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                        logging.error("Failed to insert rows after multiple attempts.")
                    rows_to_insert = []

            except requests.RequestException as e:
                logging.exception(f"Error fetching data from Jira: {e}")
                break

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery")
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                logging.error("Failed to insert rows after multiple attempts.")

        merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING `{dataset_id}.{temp_table_id}` S
        ON T.Key = S.Key  # Use "Key" for matching
        WHEN MATCHED THEN
          UPDATE SET
            T.T = S.T,  # Update IssueType
            T.Summary = S.Summary,
            T.Status = S.Status,
            T.Created = S.Created,
            T.Updated = S.Updated,
            T.Resolved = S.Resolved,
            T.Assignee = S.Assignee,
            T.TaskDefinition = S.TaskDefinition,
            T.ConsoleService = S.ConsoleService,
            T.PortProvStatus = S.PortProvStatus,
            T.RemedyTicketNumber = S.RemedyTicketNumber
        WHEN NOT MATCHED THEN
          INSERT (T, Key, Summary, Status, Created, Updated, Resolved, Assignee, TaskDefinition, ConsoleService, PortProvStatus, RemedyTicketNumber)
          VALUES (S.T, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Assignee, S.TaskDefinition, S.ConsoleService, S.PortProvStatus, S.RemedyTicketNumber)
        """
        client.query(merge_query).result()
        logging.info("Data merged successfully.")

        # Delete the temporary table after merging
        delete_temp_table(client, dataset_id, temp_table_id)

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")

if __name__ == '__main__':
    fetch_and_sync_jira_data()