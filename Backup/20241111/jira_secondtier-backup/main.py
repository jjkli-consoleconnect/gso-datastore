import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
from google.api_core.exceptions import Conflict, NotFound

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def get_field_value(field):
    """Handles various field types, returns a string representation."""
    if field is None:
        return None
    elif isinstance(field, dict):
        return field.get('value')
    elif isinstance(field, list):
        return ', '.join([str(item) for item in field])
    elif isinstance(field, bool):
        return str(field)
    else:
        return str(field)


def create_or_truncate_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        table = client.get_table(table_ref)
        logging.info(f"Table '{dataset_id}.{table_id}' found. Deleting contents...")
        client.query(f"DELETE FROM `{dataset_id}.{table_id}`").result()
        logging.info(f"Table '{dataset_id}.{table_id}' contents deleted successfully.")
    except NotFound:
        logging.info(f"Table '{dataset_id}.{table_id}' not found. Creating...")
        table = bigquery.Table(table_ref, schema=schema)
        try:
            table = client.create_table(table)
            logging.info(f"Table '{dataset_id}.{table_id}' created successfully.")
            time.sleep(5) # Add a small delay to ensure table creation is complete
        except Exception as e:
            logging.exception(f"Error creating table '{dataset_id}.{table_id}': {e}")
            return False
    except Exception as e:
        logging.exception(f"An unexpected error occurred while handling table '{dataset_id}.{table_id}': {e}")
        return False
    return True


def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://jira.pccwglobal.com/rest/api/2/search'
    jql_query = 'filter=25706'
    username = 'jjkli'
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 50
    batch_size = 100
    CHUNK_SIZE = 1000

    try:
        client = bigquery.Client()
        dataset_id = 'JIRA'
        table_id = 'SecondTier'
        temp_table_id = 'SecondTier_temp' # Use a temporary table name

        schema = [
            bigquery.SchemaField("T", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE") #Added Links field
        ]

        if not create_or_truncate_table(client, dataset_id, temp_table_id, schema):
            logging.error("Failed to create or truncate temporary table. Exiting.")
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
                issues = data.get('issues', [])
                if not issues:
                    break

                for issue in issues:
                    outward_issue_keys = ','.join([
                        link['outwardIssue']['key'] if 'outwardIssue' in link else ''
                        for link in issue['fields'].get('issuelinks', [])
                    ])

                    remedy_ticket_number = issue['fields'].get('customfield_12204', '')
                    assignee = issue['fields'].get('assignee')
                    assignee_name = assignee.get('displayName') if assignee else None

                    row = {
                        'T': issue['fields']['issuetype']['name'],
                        'Key': issue['key'],
                        'Summary': issue['fields']['summary'],
                        'Status': issue['fields']['status']['name'],
                        'Created': convert_timestamp(issue['fields']['created']),
                        'Updated': convert_timestamp(issue['fields']['updated']),
                        'Resolved': convert_timestamp(issue['fields'].get('resolutiondate')),
                        'Assignee': assignee_name,
                        'RemedyTicketNumber': remedy_ticket_number,
                        'Links': outward_issue_keys
                    }
                    rows_to_insert.append(row)
                    if len(rows_to_insert) >= CHUNK_SIZE:
                        try:
                            errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                            if errors:
                                logging.error(f"Errors inserting rows: {errors}")
                                return
                            rows_to_insert = []
                        except Exception as e:
                            logging.exception(f"Error inserting rows into BigQuery: {e}")
                            return

                start_at += max_results

            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching data from Jira: {e}")
                return

        merge_query = f"""
        MERGE `{dataset_id}.{table_id}` AS target
        USING `{dataset_id}.{temp_table_id}` AS source
        ON target.Key = source.Key
        WHEN MATCHED THEN UPDATE SET target.Summary = source.Summary,
                                         target.Status = source.Status,
                                         target.Created = source.Created,
                                         target.Updated = source.Updated,
                                         target.Resolved = source.Resolved,
                                         target.Assignee = source.Assignee,
                                         target.RemedyTicketNumber = source.RemedyTicketNumber,
                                         target.Links = source.Links,
                                         target.T = source.T
        WHEN NOT MATCHED THEN INSERT ROW
        """
        logging.info(f"Running merge query: {merge_query}")
        try:
            client.query(merge_query).result()
            logging.info("Merge completed successfully.")
        except Exception as e:
            logging.exception(f"Error running merge query: {e}")
            return

        try:
            client.delete_table(client.dataset(dataset_id).table(temp_table_id))
            logging.info("Temporary table deleted successfully.")
        except Exception as e:
            logging.exception(f"Error deleting temporary table: {e}")

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")

if __name__ == '__main__':
    fetch_and_sync_jira_data()