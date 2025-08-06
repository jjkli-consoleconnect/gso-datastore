# --- Comments-style wait_for_table and insert_rows_with_retry ---
def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception as e:
        if 'Not found' in str(e):
            return False
        logging.exception(f"Error checking existence of table '{dataset_id}.{table_id}': {e}")
        return False

def wait_for_table(client, dataset_id, table_id, retries=10, delay=5):
    for attempt in range(retries):
        if table_exists(client, dataset_id, table_id):
            logging.info(f"Table '{dataset_id}.{table_id}' is now available.")
            return True
        logging.debug(f"Waiting for table '{dataset_id}.{table_id}'. Attempt {attempt + 1}/{retries}")
        time.sleep(delay)
    logging.error(f"Table '{dataset_id}.{table_id}' is not available after {retries} attempts.")
    return False

def insert_rows_with_retry(client, dataset_id, table_id, rows, schema, retries=5, delay=5):
    for attempt in range(retries):
        try:
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            if "Not found" in str(e) or "Table is truncated" in str(e):
                logging.warning(f"Table '{dataset_id}.{table_id}' not found or truncated, retrying...")
            else:
                logging.error(f"Error inserting rows: {e}")
        if attempt < retries - 1:
            logging.info(f"Retrying insert rows into '{dataset_id}.{table_id}'. Attempt {attempt + 2}/{retries}")
            time.sleep(delay)
        else:
            logging.error(f"Failed to insert rows after {retries} attempts.")
            return False
    return False
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
        def field_sql(f):
            # Map BigQuery types to DDL types for ARRAY
            type_map = {
                "STRING": "STRING",
                "FLOAT64": "FLOAT64",
                "TIMESTAMP": "TIMESTAMP",
                "BOOL": "BOOL",
                "INT64": "INT64"
            }
            if f.mode == "REPEATED":
                sql = f"`{f.name}` ARRAY<{type_map.get(f.field_type, f.field_type)}>"
            else:
                sql = f"`{f.name}` {type_map.get(f.field_type, f.field_type)}"
                if f.mode == "REQUIRED":
                    sql += " NOT NULL"
            # NULLABLE is default
            return sql
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(field_sql(f) for f in schema)})"
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

    # --- Simplified Pipeline: Sync whatever is found in the JQL ---
    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    pipeline_name = "jira_tickets"
    run_id = str(uuid.uuid4())
    try:
        client = bigquery.Client()
        project_id = client.project
        dataset_id = 'GSO'

        # Define your JQL here (edit as needed)
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
            ') AND updated >= -3h'
        )

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
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error("Setup failed: Temp table not available.")
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        rows_to_insert = []
        total_issues = float('inf')
        start_at = 0
        max_results = 100
        issues_processed = 0
        BULK_FETCH_SIZE = 50  # Number of issues to fetch details for in parallel (tune as needed)

        def extract_sla_metrics(sla_field):
            # Returns elapsed (hours), goal (hours), breached (bool), cycles (int)
            if not isinstance(sla_field, dict):
                return None, None, None, None
            cycles = sla_field.get('completedCycles', [])
            num_cycles = len(cycles)
            if num_cycles == 0:
                return None, None, None, 0
            latest_cycle = cycles[-1]
            start_time = latest_cycle.get('startTime')
            breach_time = latest_cycle.get('breachTime')
            goal_duration = latest_cycle.get('goalDuration', {}).get('millis')
            breached = breach_time is not None
            def parse_jira_time(ts):
                try:
                    return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f%z')
                except Exception:
                    try:
                        return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z')
                    except Exception:
                        return None
            elapsed = None
            if start_time:
                start_dt = parse_jira_time(start_time)
                if breached and breach_time:
                    breach_dt = parse_jira_time(breach_time)
                    if start_dt and breach_dt:
                        elapsed = (breach_dt - start_dt).total_seconds() / 3600.0
                else:
                    now_dt = datetime.utcnow()
                    if start_dt:
                        elapsed = (now_dt - start_dt.replace(tzinfo=None)).total_seconds() / 3600.0
            goal = goal_duration / 3600000.0 if goal_duration else None
            return elapsed, goal, breached, num_cycles

        def fetch_issue_detail(issue_key):
            issue_url = f"https://consoleconnect.atlassian.net/rest/api/latest/issue/{issue_key}"
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            auth = (username, api_token)
            try:
                issue_resp = requests.get(issue_url, headers=headers, auth=auth, timeout=60)
                issue_resp.raise_for_status()
                full_issue = issue_resp.json()
                fields = full_issue.get('fields', {})
                sla_fields = {
                    'TimeToFirstResponse': fields.get('customfield_10627'),
                    'TimeToResolve': fields.get('customfield_10686'),
                    'TimeToResolution': fields.get('customfield_10668'),
                    'TimeToApproveNormalChange': fields.get('customfield_10640'),
                    'ProlongCase': fields.get('customfield_10560'),
                    'TimeToCloseAfterResolution': fields.get('customfield_10552'),
                }
                sla_metrics = {}
                for k, v in sla_fields.items():
                    elapsed, goal, breached, cycles = extract_sla_metrics(v)
                    sla_metrics[f'{k}_Elapsed'] = elapsed
                    sla_metrics[f'{k}_Goal'] = goal
                    sla_metrics[f'{k}_Breached'] = breached
                    sla_metrics[f'{k}_Cycles'] = cycles

                row = {
                    "T": None,
                    "Project": fields.get('project', {}).get('name'),
                    "Key": issue_key,
                    "Summary": fields.get('summary'),
                    "Status": fields.get('status', {}).get('name'),
                    "Created": convert_timestamp(fields.get('created')),
                    "Updated": convert_timestamp(fields.get('updated')),
                    "Resolved": convert_timestamp(fields.get('resolutiondate')),
                    "Reporter": get_field_value(fields.get('reporter')),
                    "Assignee": get_field_value(fields.get('assignee')),
                    "Component": [get_field_value(c) for c in fields.get('components', [])] if fields.get('components') else [],
                    "RemedyTicketNumber": [get_field_value(fields.get('remedyTicketNumber'))] if fields.get('remedyTicketNumber') else [],
                    "Links": get_field_value(fields.get('issuelinks')),
                    SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
                    "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    # SLA fields
                    "TimeToFirstResponse_Elapsed": sla_metrics['TimeToFirstResponse_Elapsed'],
                    "TimeToFirstResponse_Goal": sla_metrics['TimeToFirstResponse_Goal'],
                    "TimeToFirstResponse_Breached": sla_metrics['TimeToFirstResponse_Breached'],
                    "TimeToFirstResponse_Cycles": sla_metrics['TimeToFirstResponse_Cycles'],
                    "TimeToResolve_Elapsed": sla_metrics['TimeToResolve_Elapsed'],
                    "TimeToResolve_Goal": sla_metrics['TimeToResolve_Goal'],
                    "TimeToResolve_Breached": sla_metrics['TimeToResolve_Breached'],
                    "TimeToResolve_Cycles": sla_metrics['TimeToResolve_Cycles'],
                    "TimeToResolution_Elapsed": sla_metrics['TimeToResolution_Elapsed'],
                    "TimeToResolution_Goal": sla_metrics['TimeToResolution_Goal'],
                    "TimeToResolution_Breached": sla_metrics['TimeToResolution_Breached'],
                    "TimeToResolution_Cycles": sla_metrics['TimeToResolution_Cycles'],
                    "TimeToApproveNormalChange_Elapsed": sla_metrics['TimeToApproveNormalChange_Elapsed'],
                    "TimeToApproveNormalChange_Goal": sla_metrics['TimeToApproveNormalChange_Goal'],
                    "TimeToApproveNormalChange_Breached": sla_metrics['TimeToApproveNormalChange_Breached'],
                    "TimeToApproveNormalChange_Cycles": sla_metrics['TimeToApproveNormalChange_Cycles'],
                    "ProlongCase_Elapsed": sla_metrics['ProlongCase_Elapsed'],
                    "ProlongCase_Goal": sla_metrics['ProlongCase_Goal'],
                    "ProlongCase_Breached": sla_metrics['ProlongCase_Breached'],
                    "ProlongCase_Cycles": sla_metrics['ProlongCase_Cycles'],
                    "TimeToCloseAfterResolution_Elapsed": sla_metrics['TimeToCloseAfterResolution_Elapsed'],
                    "TimeToCloseAfterResolution_Goal": sla_metrics['TimeToCloseAfterResolution_Goal'],
                    "TimeToCloseAfterResolution_Breached": sla_metrics['TimeToCloseAfterResolution_Breached'],
                    "TimeToCloseAfterResolution_Cycles": sla_metrics['TimeToCloseAfterResolution_Cycles'],
                    # Escalation field
                    "AppSupEscalation": get_field_value(fields.get('customfield_11171')),
                }
                return row
            except Exception as e:
                logging.warning(f"Could not fetch full details for issue {issue_key}: {e}")
                return None

        while start_at < total_issues:
            payload = json.dumps({
                "jql": jql_query,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": ["key"]
            })
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            auth = (username, api_token)
            try:
                response = requests.post(jira_url, headers=headers, auth=auth, data=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                issues = data.get('issues', [])
                total_issues = data.get('total', 0)
                issue_keys = [issue.get('key') for issue in issues if issue.get('key')]
                # Bulk fetch issue details in parallel
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_key = {executor.submit(fetch_issue_detail, key): key for key in issue_keys}
                    for future in as_completed(future_to_key):
                        row = future.result()
                        if row:
                            rows_to_insert.append(row)
                start_at += len(issues)
                issues_processed += len(issues)
                logging.info(f"Fetched and processed {len(issues)} issues (startAt: {start_at}) out of total {total_issues}")
                if not issues:
                    break
            except requests.RequestException as e:
                logging.error(f"Error fetching issues from Jira: {e}")
                break
            except Exception as e:
                logging.error(f"Unexpected error during Jira fetch: {e}")
                break

        if rows_to_insert:
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, bq_schema, retries=5, delay=5):
                logging.error("Failed to insert rows into temp table after retries.")
                delete_temp_table(client, dataset_id, temp_table_id)
                return

        # --- Merge temp table into final table ---
        try:
            merge_fields = [
                "T", "Project", "Key", "Summary", "Status", "Created", "Updated", "Resolved", "Reporter", "Assignee", "Component", "RemedyTicketNumber", "Links", SR_REF_BQ_NAME, "SyncTime",
                "TimeToFirstResponse_Elapsed", "TimeToFirstResponse_Goal", "TimeToFirstResponse_Breached", "TimeToFirstResponse_Cycles",
                "TimeToResolve_Elapsed", "TimeToResolve_Goal", "TimeToResolve_Breached", "TimeToResolve_Cycles",
                "TimeToResolution_Elapsed", "TimeToResolution_Goal", "TimeToResolution_Breached", "TimeToResolution_Cycles",
                "TimeToApproveNormalChange_Elapsed", "TimeToApproveNormalChange_Goal", "TimeToApproveNormalChange_Breached", "TimeToApproveNormalChange_Cycles",
                "ProlongCase_Elapsed", "ProlongCase_Goal", "ProlongCase_Breached", "ProlongCase_Cycles",
                "TimeToCloseAfterResolution_Elapsed", "TimeToCloseAfterResolution_Goal", "TimeToCloseAfterResolution_Breached", "TimeToCloseAfterResolution_Cycles",
                "AppSupEscalation"
            ]
            merge_query = f'''
                MERGE `{dataset_id}.{table_id}` T
                USING `{dataset_id}.{temp_table_id}` S
                ON T.Key = S.Key
                WHEN MATCHED THEN
                  UPDATE SET
                    {', '.join([f'T.{f} = COALESCE(S.{f}, T.{f})' for f in merge_fields])}
                WHEN NOT MATCHED THEN
                  INSERT ({', '.join(merge_fields)})
                  VALUES ({', '.join([f'S.{f}' for f in merge_fields])})
            '''
            client.query(merge_query).result()
            logging.info(f"Merged temp table '{dataset_id}.{temp_table_id}' into '{dataset_id}.{table_id}'.")
        except Exception as e:
            logging.error(f"Error merging temp table into final table: {e}")

        # Now safe to delete temp table
        delete_temp_table(client, dataset_id, temp_table_id)

        # --- Log pipeline end ---
        log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "INFO", "Pipeline finished")
    except FileNotFoundError:
        logging.error("config.json not found. Please ensure it exists and contains your Jira API token.")
    except bigquery.exceptions.NotFound as e:
        logging.error(f"BigQuery resource not found (e.g., dataset or table): {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred in fetch_and_sync_jira_data: {e}")
        try:
            log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "ERROR", f"Exception: {e}", function_name="fetch_and_sync_jira_data", details=str(e))
        except Exception:
            pass
    # Log pipeline end
    try:
        log_to_bigquery(client, dataset_id, "PipelineLogs", pipeline_name, run_id, "INFO", "Pipeline finished")
    except Exception:
        pass

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
