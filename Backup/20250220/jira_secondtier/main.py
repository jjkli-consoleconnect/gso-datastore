import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
from google.api_core.exceptions import Conflict, NotFound
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.Formatter.converter = time.localtime

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

def create_temp_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
    except Exception as e:
        logging.info(f"Temporary table '{dataset_id}.{table_id}' not found, creating a new one. {e}")
    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table)
    logging.info(f"Temporary table '{dataset_id}.{table_id}' created.")


def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
    except NotFound:
        logging.warning(f"Temporary table '{dataset_id}.{table_id}' not found.")
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")


def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://jira.pccwglobal.com/rest/api/2/search'
    jql_query = 'filter=25706'  # Updated filter ID
    username = 'jjkli'  # Your Jira username - REPLACE YOUR USERNAME
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 100
    CHUNK_SIZE = 1000  # Adjust this value based on expected data volume
    RETRY_COUNT = 5  # Number of retries
    RETRY_DELAY = 5  # Delay in seconds between retries

    try:
        client = bigquery.Client()
        dataset_id = 'JIRA'
        table_id = 'SecondTier'  # Correct target table name
        temp_table_id = 'SecondTier_temp'  # Correct temporary table name

        schema = [
            bigquery.SchemaField("T", "STRING", mode="REQUIRED"),  # Use "T" for IssueType
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
        ]

        # Create or truncate the temporary table
        create_temp_table(client, dataset_id, temp_table_id, schema)


        rows_to_insert = []
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                        params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results,
                                                'fields': 'issuetype,summary,status,created,updated,resolutiondate,assignee,customfield_12204,issuelinks'},
                                        timeout=300)
                response.raise_for_status()
                data = response.json()
                logging.info(f"Fetched {len(data.get('issues', []))} issues from Jira.")

                issues = data.get('issues', [])
                if not issues:
                    break

                for issue in issues:
                    try:
                        fields = issue.get('fields', {})
                        issuelinks = fields.get('issuelinks', [])
                        issue_keys = ','.join([
                            link['inwardIssue']['key']
                            for link in issuelinks
                            if 'inwardIssue' in link
                        ])
                        remedy_ticket_number = fields.get('customfield_12204', '')
                        assignee = fields.get('assignee')
                        assignee_name = assignee.get('displayName') if assignee else None

                        row = {
                            'T': fields['issuetype']['name'],
                            'Key': issue['key'],
                            'Summary': fields['summary'],
                            'Status': fields['status']['name'],
                            'Created': convert_timestamp(fields['created']),
                            'Updated': convert_timestamp(fields['updated']),
                            'Resolved': convert_timestamp(fields.get('resolutiondate')),
                            'Assignee': assignee_name,
                            'RemedyTicketNumber': remedy_ticket_number,
                            'Links': issue_keys
                        }
                        rows_to_insert.append(row)

                        if len(rows_to_insert) >= CHUNK_SIZE:
                            try:
                                # Check if the temporary table exists before inserting rows
                                client.get_table(client.dataset(dataset_id).table(temp_table_id))
                                errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                                if errors:
                                    logging.error(f"Errors inserting rows: {errors}")
                                    return
                                rows_to_insert = []
                            except NotFound:
                                logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' not found.")
                                return
                            except Exception as e:
                                logging.exception(f"Error inserting rows into BigQuery: {e}")
                                return

                    except Exception as e:
                        logging.exception(f"Error processing issue {issue.get('key')}: {e}")

                start_at += max_results  # Increment start_at to fetch the next batch of issues

            except requests.RequestException as e:
                logging.error(f"Error fetching data from Jira: {e}")
                break

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery")
            for attempt in range(RETRY_COUNT):
                try:
                    # Check if the temporary table exists before inserting rows
                    client.get_table(client.dataset(dataset_id).table(temp_table_id))
                    errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                    if errors:
                        logging.error(f"Errors occurred while inserting rows: {errors}")
                    else:
                        logging.info(f"Inserted remaining {len(rows_to_insert)} rows into BigQuery")
                        break
                except NotFound:
                    logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' not found. Retrying in  seconds...")
                    time.sleep(RETRY_DELAY)
                except Exception as e:
                    logging.exception(f"Error inserting rows into BigQuery: {e}")
                    break

        # Verify the data in the temporary table
        logging.info("Verifying data in the temporary table...")
        verify_temp_query = f"""
        SELECT COUNT(*) as row_count
        FROM `{dataset_id}.{temp_table_id}`
        """
        verify_temp_job = client.query(verify_temp_query)
        verify_temp_result = verify_temp_job.result()
        for row in verify_temp_result:
            logging.info(f"Row count in temporary table: {row['row_count']}")


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
                    T.RemedyTicketNumber = S.RemedyTicketNumber,
                    T.Links = S.Links
            WHEN NOT MATCHED THEN
                INSERT (T, Key, Summary, Status, Created, Updated, Resolved, Assignee, RemedyTicketNumber, Links)
                VALUES (S.T, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Assignee, S.RemedyTicketNumber, S.Links)
        """
        logging.info(f"Executing merge query: {merge_query}")
        merge_job = client.query(merge_query)
        merge_job.result()  # Wait for the job to complete
        logging.info("Data merged successfully.")

        # Verify the merge result
        logging.info("Verifying merge result...")
        verify_query = f"""
        SELECT COUNT(*) as row_count
        FROM `{dataset_id}.{table_id}`
        """
        verify_job = client.query(verify_query)
        verify_result = verify_job.result()
        for row in verify_result:
            logging.info(f"Row count in target table after merge: {row['row_count']}")

        # Delete the temporary table after merging
        delete_temp_table(client, dataset_id, temp_table_id)

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")

if __name__ == '__main__':
    fetch_and_sync_jira_data()