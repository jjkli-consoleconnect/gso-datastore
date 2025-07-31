import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import base64
from shared.bq_logger import log_to_bigquery
import uuid

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEBUG = False # Set to True for detailed JQL/Params, request/response headers & bodies, DDL queries

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        return None
    except json.JSONDecodeError:
        logging.error("Error decoding config.json. Please ensure it's valid JSON.")
        logging.info("Example config.json: {\"jira_api_token\": \"YOUR_ACTUAL_TOKEN\"}")
        return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
                return None
    return None

def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        schema_ddl_parts = []
        for field in schema:
            part = f"{field.name} {field.field_type}"
            if field.mode == "REQUIRED":
                part += " NOT NULL"
            schema_ddl_parts.append(part)
        
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(schema_ddl_parts)})"
        
        # MODIFICATION: Only log the DDL query if DEBUG is True
        if DEBUG:
            logging.info(f"Executing DDL for temp table: {query}") 
        else:
            # More concise log for INFO level when not in DEBUG mode
            logging.info(f"Ensuring temporary table '{dataset_id}.{table_id}' schema.") 

        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced successfully.") # Added "successfully"
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")


def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted (or did not exist).")
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")

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

def insert_rows_with_retry(client, dataset_id, table_id, rows, retries=5, delay=5):
    if not rows:
        logging.info(f"No rows to insert into {dataset_id}.{table_id}.")
        return True
        
    table_ref = client.dataset(dataset_id).table(table_id)
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into {dataset_id}.{table_id}.")
                return True
            logging.error(f"Errors occurred while inserting {len(rows)} rows into {dataset_id}.{table_id}: {errors}")
            for error_detail in errors:
                logging.error(f"Row index: {error_detail.get('index')}, Errors: {error_detail.get('errors')}")
        except Exception as e:
            logging.exception(f"Exception during insert_rows_json into {dataset_id}.{table_id}: {e}")
        
        if attempt < retries - 1:
            logging.info(f"Retrying insert rows into table '{dataset_id}.{table_id}'. Attempt {attempt + 2}/{retries} in {delay}s")
            time.sleep(delay)
        else:
            logging.error(f"Failed to insert rows into {dataset_id}.{table_id} after {retries} attempts.")
    return False

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        logging.error("Failed to load configuration. Exiting.")
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/latest/search'
    username = 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')

    dataset_id = 'JIRAProjects'
    table_id = 'CCAS'
    log_table_id = 'PipelineLogs'
    pipeline_name = "jira_ccas"
    run_id = str(uuid.uuid4())

    # Log pipeline start
    try:
        client = bigquery.Client()
    except Exception as e:
        logging.error(f"Failed to initialize BigQuery client: {e}")
        log_to_bigquery(None, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Failed to initialize BigQuery client: {e}", function_name="fetch_and_sync_jira_data")
        return

    log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline started", function_name="fetch_and_sync_jira_data")

    try:
        actual_jql_from_filter = 'project = "Console Application Support" AND updated >= endOfDay(-8) ORDER BY updated DESC'

        start_at = 0
        max_results = 100 
        CHUNK_SIZE = 1000
        fields_to_request = ("issuetype,priority,summary,status,created,updated,resolutiondate,"
                            "reporter,assignee,creator,components,labels,resolution,"
                            "customfield_10000,customfield_10001,customfield_10002,customfield_10003,"
                            "project,customfield_10501,customfield_20325,customfield_20324,"
                            "customfield_15700,customfield_11216,customfield_11217,customfield_19601,"
                            "customfield_10300,customfield_18100,customfield_18000,"
                            "customfield_13313,issuelinks,customfield_13681,customfield_17935,"
                            "customfield_17903,customfield_16605,customfield_12204")
        client = bigquery.Client()
        dataset_id = 'JIRAProjects'
        table_id = 'CCAS'
        temp_table_id = 'CCAS_temp'
        schema = [ 
            bigquery.SchemaField("Type", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Priority", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Task_Definition", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Console_Service", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Port_Prov_Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Remedy_Ticket_Number", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Creator", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Components", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Labels", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Handover_Instruction", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Handover_Report_AS", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Resolution", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Resolution_Time", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("First_Response", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Request_Type", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"), 
            bigquery.SchemaField("Date_ordered", "STRING", mode="NULLABLE"), 
            bigquery.SchemaField("SLA_Ongoing_StartTime_jira", "STRING", mode="NULLABLE"), 
            bigquery.SchemaField("SLA_Ongoing_BreachTime_jira", "STRING", mode="NULLABLE"), 
            bigquery.SchemaField("SLA_Ongoing_Breached", "BOOLEAN", mode="NULLABLE"),
            bigquery.SchemaField("SLA_Ongoing_elapsedTime_millis", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("SLA_Ongoing_remainingTime_millis", "INTEGER", mode="NULLABLE"),
        ]

        create_or_replace_temp_table(client, dataset_id, temp_table_id, schema)
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' is not available. Exiting.")
            return

        rows_to_insert_temp = []
        total_issues_fetched_script = 0

        while True:
            logging.info(f"Fetching data from Jira using JQL, startAt: {start_at}, maxResults: {max_results}")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", f"Fetching data from Jira, startAt: {start_at}", function_name="fetch_and_sync_jira_data")

            try:
                request_headers = {
                    "Authorization": final_auth_header_value,
                    "Accept": "application/json",
                    "User-Agent": "PythonJiraSyncScript/1.9-CleanLogsDDL" 
                }
                
                params_for_request = {
                    "jql": actual_jql_from_filter,
                    "startAt": start_at,
                    "maxResults": max_results,
                    "fields": fields_to_request,
                }

                if DEBUG: 
                    logging.debug(f"Requesting URL: {jira_url}")
                    logging.debug(f"Requesting PARAMS: {json.dumps(params_for_request)}")
                    logging.debug(f"Requesting HEADERS: {request_headers}")

                response = requests.get(
                    jira_url,
                    headers=request_headers,
                    params=params_for_request,
                    timeout=300 
                )
                
                logging.info(f"JIRA RESPONSE STATUS CODE: {response.status_code}") 
                
                response_text_preview = response.text[:500] + ('...' if len(response.text) > 500 else '')
                if DEBUG or response.status_code != 200: 
                    logging.info(f"JIRA RESPONSE TEXT (preview): {response_text_preview}")
                
                is_empty_issues_array = '"issues":[]' in response.text
                log_full_text = (DEBUG and is_empty_issues_array and not ('"total":0' in response.text or '"total": 0' in response.text)) or \
                                (response.status_code != 200 and not response.ok)
                
                if log_full_text: 
                    logging.info(f"JIRA RESPONSE TEXT (full - due to error or debug condition): {response.text}")

                response.raise_for_status() 
                
                data = response.json()
                
                api_total_count = data.get('total')
                logging.info(f"Jira API reports `total` issues for this JQL: {api_total_count}") 
                
                current_issues = data.get('issues', [])
                num_current_issues = len(current_issues)
                total_issues_fetched_script += num_current_issues
                logging.info(f"Fetched {num_current_issues} issues in this batch. Total fetched by script so far: {total_issues_fetched_script}.") 

                if not current_issues:
                    logging.info("No more issues returned in this batch. Stopping pagination.")
                    break

                for issue in current_issues:
                    try:
                        fields = issue.get('fields', {})
                        if DEBUG and issue.get('key'): 
                            logging.debug(f"Processing issue {issue.get('key')}: {json.dumps(fields, indent=2)}")
                        
                        def get_nested_value(data_dict, keys, default=None):
                            temp_dict = data_dict
                            for key_part in keys:
                                if isinstance(temp_dict, dict) and key_part in temp_dict and temp_dict[key_part] is not None:
                                    temp_dict = temp_dict[key_part]
                                else:
                                    return default
                            return temp_dict

                        row_data = {
                            "Type": get_nested_value(fields, ['issuetype', 'name']),
                            "Priority": get_nested_value(fields, ['priority', 'name']),
                            "Key": issue.get('key'),
                            "Summary": fields.get('summary'),
                            "Status": get_nested_value(fields, ['status', 'name']),
                            "Created": convert_timestamp(fields.get('created')),
                            "Updated": convert_timestamp(fields.get('updated')),
                            "Resolved": convert_timestamp(fields.get('resolutiondate')),
                            "Assignee": get_nested_value(fields, ['assignee', 'displayName']),
                            "Task_Definition": get_nested_value(fields, ['customfield_17935', 'value']),
                            "Console_Service": get_nested_value(fields, ['customfield_17903', 'value']),
                            "Port_Prov_Status": get_nested_value(fields, ['customfield_16605', 'value']),
                            "Remedy_Ticket_Number": fields.get('customfield_12204'),
                            "Creator": get_nested_value(fields, ['creator', 'displayName']),
                            "Components": ', '.join([comp.get('name') for comp in fields.get('components', []) if comp and comp.get('name')]) if fields.get('components') else None,
                            "Labels": ', '.join(fields.get('labels', [])) if fields.get('labels') else None,
                            "Handover_Instruction": fields.get('customfield_18100'),
                            "Handover_Report_AS": get_nested_value(fields, ['customfield_18000', 'value']),
                            "Resolution": get_nested_value(fields, ['resolution', 'name']),
                            "Resolution_Time": get_nested_value(fields, ['customfield_20325', 'ongoingCycle', 'elapsedTime', 'friendly']),
                            "First_Response": get_nested_value(fields, ['customfield_20324', 'value']),
                            "Reporter": get_nested_value(fields, ['reporter', 'displayName']),
                            "Request_Type": get_nested_value(fields, ['customfield_10501', 'value']),
                            "Links": json.dumps(fields.get('issuelinks')) if fields.get('issuelinks') else None,
                            "Date_ordered": fields.get('customfield_13681'),
                            "SLA_Ongoing_StartTime_jira": get_nested_value(fields,['customfield_20325', 'ongoingCycle', 'startTime', 'jira']),
                            "SLA_Ongoing_BreachTime_jira": get_nested_value(fields,['customfield_20325', 'ongoingCycle', 'breachTime', 'jira']),
                            "SLA_Ongoing_Breached": get_nested_value(fields,['customfield_20325', 'ongoingCycle', 'breached']),
                            "SLA_Ongoing_elapsedTime_millis": get_nested_value(fields,['customfield_20325', 'ongoingCycle', 'elapsedTime', 'millis']),
                            "SLA_Ongoing_remainingTime_millis": get_nested_value(fields,['customfield_20325', 'ongoingCycle', 'remainingTime', 'millis']),
                        }
                        
                        if not row_data["Key"]:
                            logging.warning(f"Issue data missing 'Key' field: {issue}. Skipping this issue.")
                            continue
                        rows_to_insert_temp.append(row_data)

                        if len(rows_to_insert_temp) >= CHUNK_SIZE:
                            logging.info(f"Reached chunk size of {CHUNK_SIZE}. Inserting into temporary table...")
                            if insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert_temp):
                                rows_to_insert_temp = [] 
                            else:
                                logging.error(f"Failed to insert chunk into {temp_table_id}. Stopping further Jira fetching for this run.")
                                break 
                    
                    except Exception as e:
                        logging.exception(f"Error processing issue {issue.get('key', 'UNKNOWN_KEY')}: {e}") 
                
                if len(rows_to_insert_temp) >= CHUNK_SIZE and any(rows_to_insert_temp): 
                    logging.error("Exiting Jira fetch loop due to previous chunk insert failure.")
                    break

            except requests.exceptions.RequestException as e:
                logging.error(f"Jira API Request failed: {e}") 
                break 
            except json.JSONDecodeError as e:
                logging.error(f"Failed to decode JSON response from Jira: {e}") 
                if 'response' in locals() and hasattr(response, 'text'):
                    logging.error(f"Response text that caused error (first 500 chars): {response.text[:500]}")
                break
            except Exception as e: 
                logging.exception(f"An unexpected error occurred during Jira fetch or processing: {e}") 
                break

            if num_current_issues < max_results and api_total_count is not None and total_issues_fetched_script >= api_total_count :
                logging.info(f"Fetched all available issues ({total_issues_fetched_script} of {api_total_count}) according to Jira's total. Stopping.")
                break
            elif num_current_issues == 0 and start_at > 0 : 
                logging.info("Received 0 issues on a subsequent page. Assuming end of results.")
                break
            start_at += max_results

        if rows_to_insert_temp:
            logging.info(f"Inserting remaining {len(rows_to_insert_temp)} rows into BigQuery temporary table.")
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert_temp):
                logging.error(f"Failed to insert remaining {len(rows_to_insert_temp)} rows into {temp_table_id}.")

        logging.info(f"Finished fetching from Jira. Total issues processed by script: {total_issues_fetched_script}")
        
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
                main_table_ref = client.dataset(dataset_id).table(table_id)
                table_to_create = bigquery.Table(main_table_ref, schema=schema)
                client.create_table(table_to_create)
                logging.info(f"Main table {dataset_id}.{table_id} created.")
                if not wait_for_table(client, dataset_id, table_id, retries=5, delay=2):
                    logging.error(f"Main table {dataset_id}.{table_id} not available after creation. Merge might fail.")
            except Exception as e:
                logging.exception(f"Failed to create main table {dataset_id}.{table_id}: {e}")
                delete_temp_table(client, dataset_id, temp_table_id)
                return

        logging.info(f"Proceeding with MERGE operation into {dataset_id}.{table_id}")
        column_names = [f.name for f in schema]
        merge_set_clauses = ", ".join([f"T.`{name}` = S.row.`{name}`" for name in column_names if name != "Key"])
        insert_columns = ", ".join([f"`{name}`" for name in column_names])
        insert_values = ", ".join([f"S.row.`{name}`" for name in column_names])

        merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING (
            SELECT ARRAY_AGG(S ORDER BY S.Updated DESC LIMIT 1)[OFFSET(0)] AS row
            FROM `{dataset_id}.{temp_table_id}` S
            GROUP BY S.Key
        ) S
        ON T.Key = S.row.Key
        WHEN MATCHED THEN
            UPDATE SET {merge_set_clauses}
        WHEN NOT MATCHED THEN
            INSERT ({insert_columns})
            VALUES({insert_values})
        """
        if DEBUG: 
            logging.debug(f"Executing MERGE query: {merge_query}")
        else:
            logging.info(f"Executing MERGE query into {dataset_id}.{table_id} (Full query in DEBUG mode).")

        try:
            merge_job = client.query(merge_query)
            merge_job.result() 
            logging.info(f"Data merged successfully into {dataset_id}.{table_id}.")
            log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", f"Data merged successfully into {dataset_id}.{table_id}", function_name="fetch_and_sync_jira_data")
            if hasattr(merge_job, 'num_dml_affected_rows') and merge_job.num_dml_affected_rows is not None:
                logging.info(f"Number of rows affected by MERGE: {merge_job.num_dml_affected_rows}")
            else: 
                query_job_details = client.get_job(merge_job.job_id, location=merge_job.location)
                if hasattr(query_job_details, 'num_dml_affected_rows'):
                     logging.info(f"Merge job DML affected rows (from job details): {query_job_details.num_dml_affected_rows}")
                else:
                    logging.info("Could not retrieve num_dml_affected_rows for the merge job.")
        except Exception as e:
            logging.exception(f"Error during MERGE operation: {e}")

        logging.info("Verifying merge result...")
        verify_query = f"SELECT COUNT(*) as row_count FROM `{dataset_id}.{table_id}`"
        try:
            verify_job = client.query(verify_query)
            for row in verify_job.result():
                logging.info(f"Row count in target table '{table_id}' after merge: {row['row_count']}")
        except Exception as e:
            logging.exception(f"Error verifying target table count for '{table_id}' after merge: {e}")

        delete_temp_table(client, dataset_id, temp_table_id)

    except Exception as e:
        logging.exception(f"An unexpected error occurred in fetch_and_sync_jira_data: {e}")
        log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "ERROR", f"Exception: {e}", function_name="fetch_and_sync_jira_data", details=str(e))
        if 'client' in locals() and 'dataset_id' in locals() and 'temp_table_id' in locals():
            if table_exists(client, dataset_id, temp_table_id):
                logging.info("Attempting to clean up temporary table due to error in main function.")
                delete_temp_table(client, dataset_id, temp_table_id)

    # Log pipeline end
    log_to_bigquery(client, dataset_id, log_table_id, pipeline_name, run_id, "INFO", "Pipeline finished", function_name="fetch_and_sync_jira_data")

if __name__ == '__main__':
    fetch_and_sync_jira_data()