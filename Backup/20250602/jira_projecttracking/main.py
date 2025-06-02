import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import os
import google.auth
import base64

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.Formatter.converter = time.localtime

DEBUG = False

def load_config():
    try:
        with open('config.json') as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        with open('config.json', 'w') as f:
            json.dump({"jira_api_token": "YOUR_JIRA_API_TOKEN_HERE"}, f, indent=2)
        logging.info("A sample 'config.json' has been created. Please fill in your API token.")
        return None
    except json.JSONDecodeError:
        logging.error("Error decoding config.json. Please ensure it's valid JSON.")
        logging.info("Example config.json: {\"jira_api_token\": \"YOUR_ACTUAL_TOKEN\"}")
        return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z')
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z')
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
                return None
    return None

def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        schema_ddl_parts = []
        for field in schema:
            part = f"`{field.name}` {field.field_type}"
            if field.mode == "REQUIRED":
                part += " NOT NULL"
            schema_ddl_parts.append(part)

        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(schema_ddl_parts)})"

        if DEBUG:
            logging.info(f"Executing DDL for temp table: {query}")
        else:
            logging.info(f"Ensuring temporary table '{dataset_id}.{table_id}' schema.")

        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced successfully.")
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")
        raise

def delete_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Table '{dataset_id}.{table_id}' deleted (or did not exist).")
    except Exception as e:
        logging.exception(f"Error deleting table '{dataset_id}.{table_id}': {e}")

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception:
        logging.debug(f"Table '{dataset_id}.{table_id}' does not exist or error checking.")
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

def insert_rows_with_retry(client, table_ref, rows, retries=5, delay=5):
    if not rows:
        logging.info(f"No rows to insert into {table_ref.dataset_id}.{table_ref.table_id}.")
        return True

    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into {table_ref.dataset_id}.{table_ref.table_id}.")
                return True
            logging.error(f"Errors occurred while inserting {len(rows)} rows into {table_ref.dataset_id}.{table_ref.table_id}: {errors}")
            for error_detail in errors:
                logging.error(f"Row index: {error_detail.get('index')}, Errors: {error_detail.get('errors')}")
        except Exception as e:
            logging.exception(f"Exception during insert_rows_json into {table_ref.dataset_id}.{table_ref.table_id}: {e}")

        if attempt < retries - 1:
            logging.info(f"Retrying insert rows into table '{table_ref.dataset_id}.{table_ref.table_id}'. Attempt {attempt + 2}/{retries} in {delay}s")
            time.sleep(delay)
        else:
            logging.error(f"Failed to insert rows into {table_ref.dataset_id}.{table_ref.table_id} after {retries} attempts.")
    return False

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration. Exiting.")
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/latest/search'
    jql_query = (
        '('
        'project = "Google Contact Center AI Solution" OR '
        'project = "Knowledge Management on BMC ComAround Platform" OR '
        'project = "Console Connect Philippines Incorporate" OR '
        'project = "Digital Platform Business and Support" OR '
        'project = "GS&O Data Analytics" OR '
        'project = "GS&O Knowledge Consolidation"'
        ') AND updated >= endOfDay(-8) ORDER BY updated DESC'
    )

    username = 'jjkli@consoleconnect.com'
    api_token = config['jira_api_token']

    start_at = 0
    max_results = 100
    CHUNK_SIZE = 1000

    try:
        client = bigquery.Client()

        logging.info(f"BigQuery client initialized for project: {client.project}")
        try:
            gcp_credentials, gcp_project = google.auth.default()
            if gcp_credentials:
                logging.info(f"Detected GCP Credential Type: {type(gcp_credentials).__name__}")
                if hasattr(gcp_credentials, 'service_account_email'):
                    logging.info(f"Detected Service Account Email: {gcp_credentials.service_account_email}")
                if hasattr(gcp_credentials, 'quota_project_id') and gcp_credentials.quota_project_id:
                    logging.info(f"Detected Quota Project ID from Credentials: {gcp_credentials.quota_project_id}")
                else:
                    logging.info("Quota Project ID not found on credentials object.")
            else:
                logging.info("No explicit GCP credentials detected by google.auth.default().")
        except Exception as e:
            logging.error(f"Error during GCP credential detection: {e}")

        dataset_id = 'JIRAProjects'
        table_id = 'ProjectTracking'
        temp_table_id = 'ProjectTracking_temp'

        main_table_ref = client.dataset(dataset_id).table(table_id)
        temp_table_ref = client.dataset(dataset_id).table(temp_table_id)

        logging.info(f'Temp Table reference: {temp_table_ref.path}')

        schema = [
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
        ]

        create_or_replace_temp_table(client, dataset_id, temp_table_id, schema)
        if not wait_for_table(client, dataset_id, temp_table_id, retries=5, delay=2):
            logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' is not available. Exiting.")
            return

        all_rows = []
        total_issues_fetched = 0

        while True:
            logging.info(f'Fetching data from Jira (Cloud) starting at {start_at}...')
            try:
                response = requests.get(
                    jira_url,
                    auth=(username, api_token),
                    params={
                        'jql': jql_query,
                        'startAt': start_at,
                        'maxResults': max_results,
                        'fields': 'issuetype,project,summary,status,created,updated,resolutiondate,reporter,assignee'
                    },
                    timeout=300
                )
                response.raise_for_status()
                jira_data = response.json()
                issues = jira_data.get('issues', [])

                if not issues:
                    logging.info("No more issues returned from Jira.")
                    break

                logging.info(f"Fetched {len(issues)} issues in this batch.")
                total_issues_fetched += len(issues)

                batch_rows_to_process = []
                for issue in issues:
                    fields = issue.get('fields', {})
                    if not fields:
                        logging.warning(f"Issue {issue.get('key', 'Unknown Key')} has no fields. Skipping.")
                        continue

                    reporter = fields.get('reporter')
                    reporter_name = reporter.get('displayName', 'Unassigned') if reporter else 'Unassigned'
                    assignee = fields.get('assignee')
                    assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
                    project = fields.get('project')
                    project_name = project.get('name') if project else None

                    issuetype_data = fields.get('issuetype')
                    issuetype_name = issuetype_data.get('name') if issuetype_data else "Unknown"

                    row = {
                        'T': issuetype_name,
                        'Project': project_name,
                        'Key': issue['key'],
                        'Summary': fields.get('summary', "No Summary"),
                        'Status': fields.get('status', {}).get('name', "No Status"),
                        'Created': convert_timestamp(fields.get('created')),
                        'Updated': convert_timestamp(fields.get('updated')),
                        'Resolved': convert_timestamp(fields.get('resolutiondate')),
                        'Reporter': reporter_name,
                        'Assignee': assignee_name,
                    }

                    if not row['Created'] or not row['Updated']:
                        logging.warning(f"Issue {row['Key']} missing required timestamp (Created or Updated). Skipping row: {row}")
                        continue
                    if not row['Key'] or not row['Summary'] or not row['Status']:
                         logging.warning(f"Issue {row['Key']} missing required string field (Key, Summary, Status). Skipping row: {row}")
                         continue

                    batch_rows_to_process.append(row)

                all_rows.extend(batch_rows_to_process)

                if len(all_rows) >= CHUNK_SIZE:
                    logging.info(f"Reached chunk size of {CHUNK_SIZE}. Inserting into temporary table...")
                    if insert_rows_with_retry(client, temp_table_ref, all_rows):
                        all_rows = []
                    else:
                        logging.error(f"Failed to insert chunk into {temp_table_id}. Stopping further Jira fetching for this run.")
                        break

                total_jira_issues = jira_data.get('total', total_issues_fetched)
                if start_at + len(issues) >= total_jira_issues:
                    logging.info(f"Fetched all available issues based on Jira's total count. Total: {total_jira_issues}")
                    break

                start_at += max_results

            except requests.exceptions.HTTPError as e:
                logging.error(f'HTTP error fetching data from Jira: {e.response.status_code} - {e.response.text}')
                break
            except requests.exceptions.RequestException as e:
                logging.error(f'Error fetching data from Jira: {e}')
                break
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON response from Jira: {e}")
                logging.error(f"Response text: {response.text[:500]}...")
                break
            except Exception as e:
                logging.error(f"An unexpected error occurred during Jira fetch or processing: {e}")
                import traceback
                logging.error(traceback.format_exc())
                break

        if all_rows:
            logging.info(f"Inserting remaining {len(all_rows)} rows into BigQuery temp table...")
            if not insert_rows_with_retry(client, temp_table_ref, all_rows):
                logging.error(f"Failed to insert remaining {len(all_rows)} rows into {temp_table_id}.")

        logging.info(f"Total issues processed from Jira: {total_issues_fetched}")

        logging.info("Verifying data in the temporary table...")
        verify_temp_query = f"SELECT COUNT(*) as row_count FROM `{dataset_id}.{temp_table_id}`"
        try:
            verify_temp_job = client.query(verify_temp_query)
            for row in verify_temp_job.result():
                logging.info(f"Row count in temporary table '{temp_table_id}': {row['row_count']}")
        except Exception as e:
            logging.exception(f"Error verifying temporary table count for '{temp_table_id}': {e}")

        if not table_exists(client, dataset_id, table_id):
            logging.info(f"Main table {dataset_id}.{table_id} does not exist. Creating it with the schema.")
            try:
                table_to_create = bigquery.Table(main_table_ref, schema=schema)
                client.create_table(table_to_create)
                logging.info(f"Main table {dataset_id}.{table_id} created.")
                if not wait_for_table(client, dataset_id, table_id, retries=5, delay=2):
                    logging.error(f"Main table {dataset_id}.{table_id} not available after creation. Merge might fail.")
            except Exception as e:
                logging.exception(f"Failed to create main table {dataset_id}.{table_id}: {e}")
                delete_table(client, dataset_id, temp_table_id)
                return

        logging.info(f"Preparing to merge data from '{temp_table_id}' into '{table_id}'.")
        column_names = [f.name for f in schema]
        merge_set_clauses = ", ".join([f"T.`{name}` = S.`{name}`" for name in column_names if name != "Key"])
        insert_columns = ", ".join([f"`{name}`" for name in column_names])
        insert_values = ", ".join([f"S.`{name}`" for name in column_names])

        merge_query = f"""
            MERGE `{dataset_id}.{table_id}` AS T
            USING `{dataset_id}.{temp_table_id}` AS S
            ON T.Key = S.Key
            WHEN MATCHED THEN
                UPDATE SET {merge_set_clauses}
            WHEN NOT MATCHED THEN
                INSERT ({insert_columns})
                VALUES ({insert_values})
        """
        if DEBUG:
            logging.debug(f"Executing MERGE query: {merge_query}")
        else:
            logging.info(f"Executing MERGE query into {dataset_id}.{table_id} (Full query in DEBUG mode).")

        try:
            merge_job = client.query(merge_query)
            merge_job.result()
            logging.info(f"Data merged successfully into {dataset_id}.{table_id}.")
            if hasattr(merge_job, 'num_dml_affected_rows') and merge_job.num_dml_affected_rows is not None:
                logging.info(f"Number of rows affected by MERGE: {merge_job.num_dml_affected_rows}")
            else:
                query_job_details = client.get_job(merge_job.job_id, location=merge_job.location)
                if hasattr(query_job_details, 'num_dml_affected_rows'):
                    logging.info(f"Merge job DML affected rows (from job details): {query_job_details.num_dml_affected_rows}")
                else:
                    logging.info("Could not retrieve num_dml_affected_rows for the merge job.")
        except Exception as e:
            logging.exception(f"An error occurred during the MERGE operation: {e}")
            logging.error(merge_query)
            return

        logging.info("Verifying merge result...")
        verify_query = f"SELECT COUNT(*) as row_count FROM `{dataset_id}.{table_id}`"
        try:
            verify_job = client.query(verify_query)
            for row in verify_job.result():
                logging.info(f"Row count in target table '{table_id}' after merge: {row['row_count']}")
        except Exception as e:
            logging.exception(f"Error verifying target table count for '{table_id}' after merge: {e}")

        delete_table(client, dataset_id, temp_table_id)

    except Exception as e:
        logging.exception(f'An unexpected error occurred in fetch_and_sync_jira_data: {e}')
        if 'client' in locals() and 'dataset_id' in locals() and 'temp_table_id' in locals():
            if table_exists(client, dataset_id, temp_table_id):
                logging.info("Attempting to clean up temporary table due to error in main function.")
                delete_table(client, dataset_id, temp_table_id)

if __name__ == '__main__':
    logging.info("Starting Jira to BigQuery sync process.")
    fetch_and_sync_jira_data()
    logging.info("Jira to BigQuery sync process finished.")