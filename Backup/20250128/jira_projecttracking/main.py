import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
from tenacity import retry, stop_after_attempt, wait_exponential

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.Formatter.converter = time.localtime  # Add this line to use local time

def load_config():
    try:
        with open('config.json') as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z')
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
            return None
    return None

def get_field_value(field):
    return field.get('value') if field else None

@retry(stop=stop_after_attempt(20), wait=wait_exponential(multiplier=1, min=2, max=60))
def get_table_with_retry(client, temp_table_ref):
    try:
        return client.get_table(temp_table_ref)
    except Exception as e:
        logging.warning(f"Attempt to get table failed: {e}")
        raise

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://jira.pccwglobal.com/rest/api/2/search'
    jql_query = 'filter=25705'
    username = 'jjkli'
    api_token = config['jira_api_token']
    start_at = 0
    max_results = 50
    batch_size = 100
    CHUNK_SIZE = 1000 #Added chunking for BigQuery inserts

    try:
        client = bigquery.Client()
        dataset_id = 'JIRA'
        table_id = 'ProjectTracking'
        temp_table_id = 'ProjectTracking_temp'
        table_ref = client.dataset(dataset_id).table(table_id)
        temp_table_ref = client.dataset(dataset_id).table(temp_table_id)
        logging.info(f'Table reference: {table_ref}')
        logging.info(f'Temp Table reference: {temp_table_ref}')

        temp_table = None
        try:
            temp_table = client.get_table(temp_table_ref)
            logging.info("Temp table found. Truncating...")
            client.query(f"TRUNCATE TABLE `{temp_table_ref}`").result()
            logging.info("Temp table truncated successfully.")
        except Exception as e:
            logging.info(f"Temp table does not exist. Attempting to create: {temp_table_ref}")
            try:
                table = bigquery.Table(temp_table_ref, schema=[
                    bigquery.SchemaField('T', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('Project', 'STRING', mode='NULLABLE'),
                    bigquery.SchemaField('Key', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('Summary', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('Status', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('Created', 'TIMESTAMP', mode='REQUIRED'),
                    bigquery.SchemaField('Updated', 'TIMESTAMP', mode='REQUIRED'),
                    bigquery.SchemaField('Resolved', 'TIMESTAMP', mode='NULLABLE'),
                    bigquery.SchemaField('Reporter', 'STRING', mode='NULLABLE'),
                    bigquery.SchemaField('Assignee', 'STRING', mode='NULLABLE'),
                ])
                temp_table = client.create_table(table)
                logging.info("Temp table created successfully.")
                time.sleep(5)  # Small delay to allow table creation
            except Exception as create_e:
                logging.error(f"Failed to create temp table: {create_e}")
                return

        #Retry getting the table after creation attempt (if needed)
        if temp_table is None:
            try:
                temp_table = get_table_with_retry(client, temp_table_ref)
                logging.info("Temp table found after creation.")
            except Exception as e:
                logging.error(f"Failed to get temp table after creation attempts: {e}")
                return

        all_rows = []
        while True:
            logging.info(f'Fetching data from Jira starting at {start_at}...')
            try:
                response = requests.get(
                    jira_url,
                    auth=(username, api_token),
                    params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results},
                    timeout=300
                )
                response.raise_for_status()
                jira_data = response.json()
                issues = jira_data['issues']
                if not issues:
                    break

                for issue in issues:
                    reporter = issue['fields'].get('reporter')
                    reporter_name = reporter.get('displayName', 'Unassigned') if reporter else 'Unassigned'
                    assignee = issue['fields'].get('assignee')
                    assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
                    project = issue['fields'].get('project')
                    project_name = project.get('name') if project else 'Unassigned'

                    row = {
                        'T': issue['fields']['issuetype']['name'],
                        'Project': project_name,
                        'Key': issue['key'],
                        'Summary': issue['fields']['summary'],
                        'Status': issue['fields']['status']['name'],
                        'Created': convert_timestamp(issue['fields']['created']),
                        'Updated': convert_timestamp(issue['fields']['updated']),
                        'Resolved': convert_timestamp(issue['fields'].get('resolutiondate')),
                        'Reporter': reporter_name,
                        'Assignee': assignee_name,
                    }
                    all_rows.append(row)
                    if len(all_rows) >= CHUNK_SIZE:
                        errors = client.insert_rows_json(temp_table, all_rows)
                        if errors:
                            logging.error(f'Error inserting data into BigQuery: {errors}')
                            return
                        all_rows = []

                if all_rows: #Handle the last batch
                    errors = client.insert_rows_json(temp_table, all_rows)
                    if errors:
                        logging.error(f'Error inserting data into BigQuery: {errors}')
                        return
                    all_rows = []

                start_at += max_results

            except requests.exceptions.RequestException as e:
                logging.error(f'Error fetching data from Jira: {e}')
                return

        merge_query = f"""
        MERGE `{table_ref}` AS T
        USING `{temp_table_ref}` AS S
        ON T.Key = S.Key
        WHEN MATCHED THEN
            UPDATE SET T.Summary = S.Summary,
                         T.Status = S.Status,
                         T.Created = S.Created,
                         T.Updated = S.Updated,
                         T.Resolved = S.Resolved,
                         T.Reporter = S.Reporter,
                         T.Assignee = S.Assignee,
                         T.T = S.T,
                         T.Project = S.Project
        WHEN NOT MATCHED THEN
            INSERT (T, Key, Summary, Status, Created, Updated, Resolved, Reporter, Assignee, Project)
            VALUES (S.T, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, S.Project);
        """
        logging.info(f'Running merge query: {merge_query}')
        merge_job = client.query(merge_query)
        merge_job.result()
        logging.info('Merge completed successfully.')

        client.delete_table(temp_table_ref)
        logging.info('Temporary table deleted successfully.')

    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching data from Jira: {e}')
    except Exception as e:
        logging.error(f'Unexpected error: {e}')

if __name__ == '__main__':
    fetch_and_sync_jira_data()