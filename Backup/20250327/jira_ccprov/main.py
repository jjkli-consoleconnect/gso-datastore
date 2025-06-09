import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os
from google.api_core.exceptions import Conflict, NotFound

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
    except NotFound:
        logging.info(f"Temporary table '{dataset_id}.{table_id}' not found, creating a new one.")
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
    jql_query = 'filter=25713'  # Updated filter ID
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
        table_id = 'project_CCPROV'  # Correct target table name
        temp_table_id = 'project_CCPROV_temp'  # Correct temporary table name

        schema = [
            bigquery.SchemaField("T", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Project", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Creator", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Port_Prov_Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("On_Board_Checklist", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Onboard_Category", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Insight_ID", "STRING", mode="NULLABLE"),
        ]

        # Create the temporary table
        create_temp_table(client, dataset_id, temp_table_id, schema)

        rows_to_insert = []
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                        params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results,
                                                'fields': 'issuetype,project,summary,status,created,updated,resolutiondate,reporter,assignee,creator,customfield_10000,customfield_10001,customfield_10002,customfield_10003'},
                                        timeout=300)
                response.raise_for_status()
                data = response.json()
                issues = data.get('issues', [])
                if not issues:
                    break

                for issue in issues:
                    fields = issue.get('fields')
                    if fields is None:
                        logging.warning(f"Issue {issue.get('key', 'N/A')} is missing 'fields' key. Skipping...")
                        continue

                    row = {
                        'T': fields['issuetype']['name'],
                        'Project': fields['project']['name'],
                        'Key': issue['key'],
                        'Summary': fields['summary'],
                        'Status': fields['status']['name'],
                        'Created': convert_timestamp(fields['created']),
                        'Updated': convert_timestamp(fields['updated']),
                        'Resolved': convert_timestamp(fields.get('resolutiondate')),
                        'Reporter': fields['reporter']['displayName'] if fields.get('reporter') else None,
                        'Assignee': fields['assignee']['displayName'] if fields.get('assignee') else None,
                        'Creator': fields['creator']['displayName'] if fields.get('creator') else None,
                        'Port_Prov_Status': fields.get('customfield_10000'),
                        'On_Board_Checklist': get_field_value(fields.get('customfield_10001')),
                        'Onboard_Category': fields.get('customfield_10002'),
                        'Insight_ID': fields.get('customfield_10003')
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

                start_at += max_results  # Increment start_at to fetch the next batch of issues

            except requests.RequestException as e:
                logging.error(f"Error fetching data from Jira: {e}")
                break

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery")
            for attempt in range(RETRY_COUNT):
                try:
                    errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                    if errors:
                        logging.error(f"Errors occurred while inserting rows: {errors}")
                    else:
                        logging.info(f"Inserted remaining {len(rows_to_insert)} rows into BigQuery")
                        break
                except NotFound:
                    logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' not found. Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                except Exception as e:
                    logging.exception(f"Error inserting rows into BigQuery: {e}")
                    time.sleep(RETRY_DELAY)
                    
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
            T.Project = S.Project,
            T.Summary = S.Summary,
            T.Status = S.Status,
            T.Created = S.Created,
            T.Updated = S.Updated,
            T.Resolved = S.Resolved,
            T.Reporter = S.Reporter,
            T.Assignee = S.Assignee,
            T.Creator = S.Creator,
            T.`Port Prov Status` = S.Port_Prov_Status,
            T.`On-Board Checklist` = S.On_Board_Checklist,
            T.`Onboard Category` = S.Onboard_Category,
            T.`Insight ID` = S.Insight_ID
        WHEN NOT MATCHED THEN
            INSERT (T, Project, Key, Summary, Status, Created, Updated, Resolved, Reporter, Assignee, Creator, `Port Prov Status`, `On-Board Checklist`, `Onboard Category`, `Insight ID`)
            VALUES (S.T, S.Project, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, S.Creator, S.Port_Prov_Status, S.On_Board_Checklist, S.Onboard_Category, S.Insight_ID)
        """
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


def main():
    fetch_and_sync_jira_data()


if __name__ == "__main__":
    main()