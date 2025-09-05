import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError
import re

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
            # Primary format with microseconds
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            # Fallback format without microseconds
            try:
                return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logging.warning(f"Invalid timestamp format, cannot parse: {timestamp}, Error: {e}")
                return None
    return None

def get_field_value(field):
    """Handles various field types, returns a string representation."""
    if field is None:
        return None
    elif isinstance(field, dict):
        # Prioritize 'value', then 'name', then 'displayName' for dictionaries
        return field.get('value') or field.get('name') or field.get('displayName')
    elif isinstance(field, list):
        # Ensure items in list are dictionaries before trying .get()
        return ', '.join([str(item.get('value') or item.get('name') or item.get('displayName') if isinstance(item, dict) else item) for item in field])
    elif isinstance(field, bool):
        return str(field)
    else:
        return str(field)

def create_temp_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    max_wait_seconds = 60
    poll_interval_seconds = 5

    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted or did not exist.")
    except Exception as e:
        logging.warning(f"Issue during deletion of temp table '{dataset_id}.{table_id}': {e}")
    
    table = bigquery.Table(table_ref, schema=schema)
    try:
        logging.info(f"Attempting to create temporary table '{dataset_id}.{table_id}'.")
        client.create_table(table)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' initiated creation.")
        
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            try:
                client.get_table(table_ref)
                logging.info(f"Temporary table '{dataset_id}.{table_id}' is ready.")
                return
            except NotFound:
                logging.info(f"Table '{dataset_id}.{table_id}' not found yet, retrying in {poll_interval_seconds}s...")
            except GoogleAPIError as api_err:
                logging.warning(f"API error while checking table '{dataset_id}.{table_id}' status: {api_err}. Retrying in {poll_interval_seconds}s...")
            time.sleep(poll_interval_seconds)
        
        logging.error(f"Temporary table '{dataset_id}.{table_id}' could not be confirmed as ready after {max_wait_seconds} seconds.")
        raise RuntimeError(f"Failed to confirm readiness of temporary table '{dataset_id}.{table_id}'.")

    except Conflict:
        logging.info(f"Temporary table '{dataset_id}.{table_id}' already exists. Attempting to confirm readiness.")
        try:
            client.get_table(table_ref)
            logging.info(f"Existing temporary table '{dataset_id}.{table_id}' confirmed ready.")
            return
        except Exception as e:
            logging.error(f"Existing temporary table '{dataset_id}.{table_id}' not accessible: {e}")
            raise
    except Exception as e:
        logging.error(f"Failed to create temporary table '{dataset_id}.{table_id}': {e}")
        raise

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
    except Exception as e:
        logging.exception(f"Unexpected error deleting temporary table '{dataset_id}.{table_id}': {e}")


def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    
    jql_query = (
        '(project = "Console Application Support" OR project = TAC OR project = "Global Service Delivery Team" OR project = "Console Connect Provisioning" OR project = "VOICE - CE" OR project = "Transmission TX-CE" OR project = "Mobility SMS - CE" OR project = "IOT CE" OR project = "Managed Security Services")'  
        'AND updated >= endOfDay(-3)'
    )
    
    username = 'jjkli@consoleconnect.com' 
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 100
    CHUNK_SIZE = 1000
    RETRY_COUNT = 5
    RETRY_DELAY = 5

    # --- Configuration for the new custom field ---
    SR_REF_JIRA_ID = 'customfield_10382' # Jira internal ID for the Service Request Reference field
    SR_REF_BQ_NAME = 'SR_Ref'            # Desired BigQuery column name
    # ---------------------------------------------
    
    try:
        client = bigquery.Client()
        project_id = client.project
        dataset_id = 'GSO'
        table_id = 'TierTwo' 
        temp_table_id = 'TierTwo_temp' 

        # 1. BigQuery Schema: Add a new SchemaField for the SR_Ref custom field
        bq_schema = [ 
            bigquery.SchemaField("T", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="REPEATED"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SR_REF_BQ_NAME, "STRING", mode="NULLABLE"),
            # SyncTime removed from schema, handled by BigQuery default
        ]
        create_temp_table(client, dataset_id, temp_table_id, bq_schema)
        time.sleep(2)  # Wait 2 seconds for table propagation

        rows_to_insert = []
        total_issues_fetched = 0
        
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            
            # 2. Jira API Request: Add SR_REF_JIRA_ID to the fields_to_request
            fields_to_request = f'issuetype,summary,status,created,updated,resolutiondate,assignee,customfield_10647,issuelinks,{SR_REF_JIRA_ID}'

            params = {
                'jql': jql_query,
                'startAt': start_at,
                'maxResults': max_results,
                'fields': fields_to_request
            }

            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                         params=params,
                                         timeout=300)
                response.raise_for_status()
                data = response.json()
                
                fetched_count = len(data.get('issues', []))
                api_total = data.get('total', 0)
                logging.info(f"Fetched {fetched_count} issues from Jira (Page startAt: {start_at}, API total: {api_total}).")

                issues = data.get('issues', [])
                if not issues:
                    logging.info("No more issues returned from Jira, ending fetch loop.")
                    break

                for issue in issues:
                    try:
                        fields = issue.get('fields', {})
                        issuelinks = fields.get('issuelinks', [])
                        issue_keys_list = []
                        for link in issuelinks:
                            if 'inwardIssue' in link and link['inwardIssue'] and 'key' in link['inwardIssue']:
                                issue_keys_list.append(link['inwardIssue']['key'])
                            elif 'outwardIssue' in link and link['outwardIssue'] and 'key' in link['outwardIssue']:
                                issue_keys_list.append(link['outwardIssue']['key'])
                        
                        issue_keys = ','.join(issue_keys_list) if issue_keys_list else None

                        remedy_ticket_number = fields.get('customfield_10647') 
                        
                        assignee_data = fields.get('assignee')
                        assignee_name = assignee_data.get('displayName') if assignee_data else None

                        issuetype_data = fields.get('issuetype')
                        issuetype_name = issuetype_data.get('name') if issuetype_data else None

                        status_data = fields.get('status')
                        status_name = status_data.get('name') if status_data else None

                        # 3. Data Extraction: Get value for the SR_Ref custom field
                        sr_ref_value = get_field_value(fields.get(SR_REF_JIRA_ID))
                        sr_ref_value = transform_sr_ref(sr_ref_value)  # <--- Apply transformation

                        row = {
                            'T': issuetype_name,
                            'Key': issue['key'],
                            'Summary': fields.get('summary'),
                            'Status': status_name,
                            'Created': convert_timestamp(fields.get('created')),
                            'Updated': convert_timestamp(fields.get('updated')),
                            'Resolved': convert_timestamp(fields.get('resolutiondate')),
                            'Assignee': assignee_name,
                            'RemedyTicketNumber': extract_incident_numbers(remedy_ticket_number),
                            'Links': issue_keys,
                            SR_REF_BQ_NAME: sr_ref_value,
                            # SyncTime removed, handled by BigQuery default
                        }
                        
                        required_fields = ['T', 'Key', 'Summary', 'Status', 'Created', 'Updated']
                        if any(row[field] is None for field in required_fields):
                            logging.error(f"Skipping row due to missing required fields: {row}")
                            continue
                        rows_to_insert.append(row)

                        if len(rows_to_insert) >= CHUNK_SIZE:
                            logging.info(f"Inserting chunk of {len(rows_to_insert)} rows into BigQuery temp table.")
                            for attempt in range(RETRY_COUNT):
                                try:
                                    errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                                    if errors:
                                        logging.error(f"Errors inserting rows (attempt {attempt + 1}/{RETRY_COUNT}): {errors}")
                                    else:
                                        logging.info(f"Successfully inserted {len(rows_to_insert)} rows (attempt {attempt + 1}/{RETRY_COUNT}).")
                                        rows_to_insert = [] 
                                        break 
                                except Exception as e: 
                                    logging.exception(f"Error inserting chunk into BigQuery (attempt {attempt + 1}/{RETRY_COUNT}): {e}")
                                    if attempt < RETRY_COUNT - 1:
                                        logging.info(f"Retrying chunk insertion in {RETRY_DELAY} seconds...")
                                        time.sleep(RETRY_DELAY)
                                    else:
                                        logging.error(f"Failed to insert chunk after {RETRY_COUNT} attempts. This chunk will likely be lost.")
                                        rows_to_insert = []
                                        break 
                            

                    except Exception as e:
                        logging.exception(f"Error processing issue {issue.get('key', 'N/A')}: {e}")

                start_at += len(issues)
                total_issues_fetched += len(issues)

                if start_at >= api_total:
                    logging.info(f"Reached API total. All {api_total} issues expected have been reviewed.")
                    break
                if not issues: 
                    logging.info("No issues fetched on this page, stopping.")
                    break

            except requests.exceptions.HTTPError as e:
                logging.error(f"HTTP error fetching data from Jira: {e.response.status_code} - {e.response.text}")
                if e.response.status_code == 401:
                    logging.error("Jira Authentication Failed (401). Check username/API token and permissions.")
                elif e.response.status_code == 400:
                    logging.error(f"Jira API Bad Request (400). Likely an issue with JQL or parameters. JQL used: {jql_query}")
                break 
            except requests.RequestException as e:
                logging.error(f"Request error fetching data from Jira: {e}")
                break 

        logging.info(f"Total issues processed from Jira: {total_issues_fetched}")

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery temp table.")
            for attempt in range(RETRY_COUNT):
                try:
                    errors = client.insert_rows_json(client.dataset(dataset_id).table(temp_table_id), rows_to_insert)
                    if not errors:
                        logging.info(f"Successfully inserted remaining {len(rows_to_insert)} rows.")
                        rows_to_insert = []
                        break
                    else:
                        logging.error(f"Errors inserting remaining rows (attempt {attempt + 1}/{RETRY_COUNT}): {errors}")
                except Exception as e: 
                    logging.exception(f"Error inserting remaining rows (attempt {attempt + 1}/{RETRY_COUNT}): {e}")
                
                if attempt < RETRY_COUNT - 1:
                    logging.info(f"Retrying remaining rows insertion in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else: 
                    logging.error(f"Failed to insert {len(rows_to_insert)} remaining rows after {RETRY_COUNT} attempts. Data loss may occur.")

        logging.info("Verifying data in the temporary table...")
        verify_temp_query = f"SELECT COUNT(*) as row_count FROM `{project_id}.{dataset_id}.{temp_table_id}`"
        try:
            verify_temp_job = client.query(verify_temp_query)
            verify_temp_result = list(verify_temp_job.result())
            temp_table_row_count = 0
            if verify_temp_result:
                temp_table_row_count = verify_temp_result[0]['row_count']
            logging.info(f"Row count in temporary table '{temp_table_id}': {temp_table_row_count}")
            if temp_table_row_count == 0 and total_issues_fetched > 0:
                   logging.warning("Temp table is empty but issues were fetched. Check insertion logic and errors, or if all fetched issues were filtered out before insertion.")
        except Exception as e:
            logging.error(f"Could not verify temp table count: {e}")
            temp_table_row_count = -1 

        if temp_table_row_count > 0:
            logging.info(f"Proceeding with MERGE operation as temp table has {temp_table_row_count} rows.")
            # 4. BigQuery MERGE Statement: Include the new SR_Ref column
            merge_query = f"""
                MERGE `{project_id}.{dataset_id}.{table_id}` T
                USING `{project_id}.{dataset_id}.{temp_table_id}` S
                ON T.Key = S.Key
                WHEN MATCHED THEN
                    UPDATE SET
                        T.T = S.T,
                        T.Summary = S.Summary,
                        T.Status = S.Status,
                        T.Created = S.Created,
                        T.Updated = S.Updated,
                        T.Resolved = S.Resolved,
                        T.Assignee = S.Assignee,
                        T.RemedyTicketNumber = S.RemedyTicketNumber,
                        T.Links = S.Links,
                        T.{SR_REF_BQ_NAME} = S.{SR_REF_BQ_NAME},
                        T.SyncTime = CURRENT_TIMESTAMP() -- Set by BigQuery
                WHEN NOT MATCHED THEN
                    INSERT (T, Key, Summary, Status, Created, Updated, Resolved, Assignee, RemedyTicketNumber, Links, {SR_REF_BQ_NAME}, SyncTime)
                    VALUES (S.T, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Assignee, S.RemedyTicketNumber, S.Links, S.{SR_REF_BQ_NAME}, CURRENT_TIMESTAMP())
            """
            logging.info(f"Executing merge query...")
            try:
                merge_job = client.query(merge_query)
                merge_job.result()
                logging.info(f"Data merged successfully. Affected rows: {merge_job.num_dml_affected_rows if hasattr(merge_job, 'num_dml_affected_rows') else 'N/A'}")

                logging.info("Verifying merge result...")
                verify_query = f"SELECT COUNT(*) as row_count FROM `{project_id}.{dataset_id}.{table_id}`"
                verify_job = client.query(verify_query)
                verify_result = verify_job.result()
                for row in verify_result:
                    logging.info(f"Row count in target table '{table_id}' after merge: {row['row_count']}")
            except Exception as e:
                logging.exception(f"Error during MERGE operation: {e}")
        elif temp_table_row_count == 0:
            logging.info("Skipping MERGE operation as temporary table is empty.")
        else:
            logging.warning("Skipping MERGE operation due to an error in verifying temp table count.")

        delete_temp_table(client, dataset_id, temp_table_id)

    except FileNotFoundError:
        logging.error("config.json not found. Please ensure it exists and contains your Jira API token.")
    except bigquery.exceptions.NotFound as e:
        logging.error(f"BigQuery resource not found (e.g., dataset or table): {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred in fetch_and_sync_jira_data: {e}")

def ensure_temp_table_exists(client, dataset_id, temp_table_id, bq_schema):
    table_ref = client.dataset(dataset_id).table(temp_table_id)
    try:
        client.get_table(table_ref)
    except NotFound:
        logging.warning(f"Temp table '{dataset_id}.{temp_table_id}' not found, recreating.")
        create_temp_table(client, dataset_id, temp_table_id, bq_schema)

def transform_sr_ref(value):
    """Remove leading/trailing spaces and all 'SR' (case-insensitive) from the value."""
    if value is None:
        return None
    # Remove leading/trailing spaces
    value = str(value).strip()
    # Remove all occurrences of 'SR' (case-insensitive)
    value = value.replace('SR', '').replace('sr', '').replace('Sr', '').replace('sR', '')
    return value

def extract_incident_numbers(remedy_ticket_number):
    """Extracts all incident numbers matching INC followed by 9+ digits."""
    if not remedy_ticket_number:
        return []
    return re.findall(r'INC\d{9,}', str(remedy_ticket_number))

if __name__ == '__main__':
    fetch_and_sync_jira_data()
