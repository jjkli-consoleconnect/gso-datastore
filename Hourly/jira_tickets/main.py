import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime, timedelta
import time
import uuid
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError
import re
from bq_logger import log_to_bigquery

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


# --- Comments-style temp table creation ---
def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(f'`{f.name}` {f.field_type}' for f in schema)})"
        logging.debug(f"Executing query: {query}")
        client.query(query).result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced.")
        return True
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")
        return False


# --- Comments-style temp table deletion ---
def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
        return True
    except Exception as e:
        if 'Not found' in str(e):
            logging.warning(f"Temporary table '{dataset_id}.{table_id}' not found during deletion attempt, likely already gone or never created.")
            return True
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False


def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/latest/search'

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

    # --- Pipeline/Progress Table Setup ---
    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    pipeline_name = "jira_tickets"
    run_id = str(uuid.uuid4())
    window_days = 7
    min_ts = datetime(2025, 1, 1)
    now = datetime.utcnow()
    progress_table = f"{table_id}_progress"
    progress_schema = [
        bigquery.SchemaField("WindowStart", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("WindowEnd", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("LastRun", "TIMESTAMP", mode="NULLABLE"),
    ]
    try:
        client = bigquery.Client()
        project_id = client.project
        dataset_id = 'GSO'
        # Ensure progress table exists
        def table_exists(client, dataset_id, table_id):
            try:
                client.get_table(f"{dataset_id}.{table_id}")
                return True
            except Exception as e:
                if 'Not found' in str(e):
                    return False
                return False
        if not table_exists(client, dataset_id, progress_table):
            create_or_replace_temp_table(client, dataset_id, progress_table, progress_schema)

        # Find the earliest window with status not 'complete'
        progress_query = f"SELECT WindowStart, WindowEnd FROM `{dataset_id}.{progress_table}` WHERE Status != 'complete' ORDER BY WindowStart ASC LIMIT 1"
        window_start = None
        window_end = None
        try:
            result = client.query(progress_query).result()
            for row in result:
                window_start = row.WindowStart
                window_end = row.WindowEnd
                break
        except Exception as e:
            logging.warning(f"Could not query progress table: {e}")

        if window_start and window_end:
            window_end_candidate = window_end
        else:
            latest_query = f"SELECT WindowEnd FROM `{dataset_id}.{progress_table}` ORDER BY WindowEnd DESC LIMIT 1"
            latest_end = None
            try:
                result = client.query(latest_query).result()
                for row in result:
                    latest_end = row.WindowEnd
                    break
            except Exception as e:
                logging.warning(f"Could not query for latest window: {e}")
            if latest_end:
                window_start = latest_end
            else:
                window_start = min_ts
            window_end_candidate = window_start + timedelta(days=window_days)

        if hasattr(window_end_candidate, 'tzinfo') and window_end_candidate.tzinfo is not None and window_end_candidate.tzinfo.utcoffset(window_end_candidate) is not None:
            window_end_candidate_naive = window_end_candidate.replace(tzinfo=None)
        else:
            window_end_candidate_naive = window_end_candidate

        if now.tzinfo is not None and now.tzinfo.utcoffset(now) is not None:
            now_naive = now.replace(tzinfo=None)
        else:
            now_naive = now

        window_end = min(window_end_candidate_naive, now_naive)

        # Mark this window as in_progress
        try:
            merge_query = f'''
                MERGE `{dataset_id}.{progress_table}` T
                USING (SELECT TIMESTAMP('{window_start}') AS WindowStart, TIMESTAMP('{window_end}') AS WindowEnd) S
                ON T.WindowStart = S.WindowStart AND T.WindowEnd = S.WindowEnd
                WHEN MATCHED THEN
                  UPDATE SET Status = 'in_progress', LastRun = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN
                  INSERT (WindowStart, WindowEnd, Status, LastRun)
                  VALUES (S.WindowStart, S.WindowEnd, 'in_progress', CURRENT_TIMESTAMP())
            '''
            client.query(merge_query).result()
            logging.info(f"Progress table updated: window {window_start} to {window_end} marked as in_progress.")
        except Exception as e:
            logging.warning(f"Could not update progress table: {e}")

        # --- Main Pipeline Logic ---
        # ...existing code for schema, temp table, and sync logic...
        # Replace jql_query time window with progress window
        jql_query = (
            '(' 
            'project = "GS&O Data Analytics" OR '
            'project = "GS&O Tool Automation" OR '
            'project = "GS&O Knowledge Consolidation" OR '
            'project = "Google Contact Center AI Solution" OR '
            'project = TAC OR '
            'project = "Console Application Support" OR '
            'project = "VOICE - CE" OR '
            'project = "IOT CE" OR '
            'project = "Console Connect Provisioning" OR '
            'project = "Global Service Delivery Team"'
            f') AND updated >= "{window_start.strftime("%Y/%m/%d %H:%M")}" AND updated < "{window_end.strftime("%Y/%m/%d %H:%M")}"'
        )
        # ...existing code for fetching, inserting, merging...
        # --- Log pipeline start ---
        log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "INFO", "Pipeline started")

        # Create temp table for this run
        bq_schema = [
            bigquery.SchemaField("T", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Project", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Component", "STRING", mode="REPEATED"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="REPEATED"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SR_REF_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
            # SLA fields: elapsed, goal, breached, cycle count
            bigquery.SchemaField("TimeToFirstResponse_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Elapsed", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Goal", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("AppSupEscalation", "STRING", mode="NULLABLE"),
        ]
        if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
            logging.error("Setup failed: Could not create temp table.")
            return

        # ...existing code for fetching, inserting, merging...
        # At the end, delete temp table
        delete_temp_table(client, dataset_id, temp_table_id)


        # --- Comments-style sync_success logic ---
        sync_success = False
        temp_table_row_count = 0
        # After fetching and inserting, verify temp table row count
        verify_temp_query = f"SELECT COUNT(*) as row_count FROM `{project_id}.{dataset_id}.{temp_table_id}`"
        try:
            verify_temp_job = client.query(verify_temp_query)
            verify_temp_result = list(verify_temp_job.result())
            if verify_temp_result:
                temp_table_row_count = verify_temp_result[0]['row_count']
        except Exception as e:
            logging.error(f"Could not verify temp table count: {e}")
            temp_table_row_count = -1

        if temp_table_row_count > 0:
            sync_success = True

        # --- Mark window as complete or failed ---
        if sync_success:
            try:
                complete_query = f'''
                    UPDATE `{dataset_id}.{progress_table}`
                    SET Status = 'complete', LastRun = CURRENT_TIMESTAMP()
                    WHERE WindowStart = TIMESTAMP('{window_start}') AND WindowEnd = TIMESTAMP('{window_end}')
                '''
                client.query(complete_query).result()
                logging.info(f"Progress table updated: window {window_start} to {window_end} marked as complete.")
            except Exception as e:
                logging.warning(f"Could not mark window as complete: {e}")
        else:
            try:
                fail_query = f'''
                    UPDATE `{dataset_id}.{progress_table}`
                    SET Status = 'failed', LastRun = CURRENT_TIMESTAMP()
                    WHERE WindowStart = TIMESTAMP('{window_start}') AND WindowEnd = TIMESTAMP('{window_end}')
                '''
                client.query(fail_query).result()
                logging.info(f"Progress table updated: window {window_start} to {window_end} marked as failed.")
            except Exception as e:
                logging.warning(f"Could not mark window as failed: {e}")

        # --- Log pipeline end ---
        log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "INFO", "Pipeline finished")
    except FileNotFoundError:
        logging.error("config.json not found. Please ensure it exists and contains your Jira API token.")
    except bigquery.exceptions.NotFound as e:
        logging.error(f"BigQuery resource not found (e.g., dataset or table): {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred in fetch_and_sync_jira_data: {e}")
        log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "ERROR", f"Exception: {e}", function_name="fetch_and_sync_jira_data", details=str(e))
    # Log pipeline end
    log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "INFO", "Pipeline finished")

def ensure_temp_table_exists(client, dataset_id, temp_table_id, bq_schema):
    table_ref = client.dataset(dataset_id).table(temp_table_id)
    try:
        client.get_table(table_ref)
    except NotFound:
        logging.warning(f"Temp table '{dataset_id}.{temp_table_id}' not found, recreating.")
        create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema)

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
