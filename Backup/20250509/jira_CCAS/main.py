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
    jql_query = 'filter=26107'  # Updated filter ID
    username = 'jjkli'  # Your Jira username - REPLACE YOUR USERNAME
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 100
    CHUNK_SIZE = 1000  # Adjust this value based on expected data volume

    try:
        client = bigquery.Client()
        dataset_id = 'JIRAProjects'
        table_id = 'CCAS'
        temp_table_id = 'CCAS_temp'

        schema = [
            bigquery.SchemaField("Type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Priority", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="REQUIRED"),
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


        # Create or replace the temporary table
        create_or_replace_temp_table(client, dataset_id, temp_table_id, schema)

        # Wait for the temporary table to be available
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' is not available.")
            return

        rows_to_insert = []
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                         params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results,
                                                'fields': 'issuetype,priority,summary,status,created,updated,resolutiondate,reporter,assignee,creator,customfield_10000,customfield_10001,customfield_10002,customfield_10003,project,customfield_10501,customfield_20325,customfield_20324,customfield_15700,customfield_11216,customfield_11217,customfield_19601,customfield_10300,components,labels,customfield_18100,customfield_18000,resolution,customfield_13313,issuelinks,customfield_13681,customfield_17935,customfield_17903,customfield_16605,customfield_12204'},
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
                        if DEBUG:
                            logging.debug(f"Fields for issue {issue.get('key')}: {json.dumps(fields, indent=2)}")  # Log fields for debugging
                        rows_to_insert.append({
                            "Type": fields.get('issuetype', {}).get('name') if fields.get('issuetype') else None,
                            "Priority": fields.get('priority', {}).get('name') if fields.get('priority') else None,
                            "Key": issue.get('key'),
                            "Summary": fields.get('summary') if fields.get('summary') else None,
                            "Status": fields.get('status', {}).get('name') if fields.get('status') else None,
                            "Created": convert_timestamp(fields.get('created')),
                            "Updated": convert_timestamp(fields.get('updated')),
                            "Resolved": convert_timestamp(fields.get('resolutiondate')),
                            "Assignee": fields.get('assignee', {}).get('displayName') if fields.get('assignee') else None,
                            "Task_Definition": fields.get('customfield_17935', {}).get('value') if fields.get('customfield_17935') else None,
                            "Console_Service": fields.get('customfield_17903', {}).get('value') if fields.get('customfield_17903') else None,
                            "Port_Prov_Status": fields.get('customfield_16605', {}).get('value') if fields.get('customfield_16605') else None,
                            "Remedy_Ticket_Number": fields.get('customfield_12204') if fields.get('customfield_12204') else None,
                            "Creator": fields.get('creator', {}).get('displayName') if fields.get('creator') else None,
                            "Components": ', '.join([comp.get('name') for comp in fields.get('components', [])]) if fields.get('components') else None,
                            "Labels": ', '.join(fields.get('labels', [])) if fields.get('labels') else None,
                            "Handover_Instruction": fields.get('customfield_18100') if fields.get('customfield_18100') else None,
                            "Handover_Report_AS": fields.get('customfield_18000', {}).get('value') if fields.get('customfield_18000') else None,
                            "Resolution": fields.get('resolution', {}).get('name') if fields.get('resolution') else None,
                            "Resolution_Time": fields.get('customfield_20325', {}).get('ongoingCycle', {}).get('elapsedTime', {}).get('friendly') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle', {}).get('elapsedTime') else None,
                            "First_Response": fields.get('customfield_20324', {}).get('value') if fields.get('customfield_20324') else None,
                            "Reporter": fields.get('reporter', {}).get('displayName') if fields.get('reporter') else None,
                             "Request_Type": fields.get('customfield_10501', {}).get('value') if fields.get('customfield_10501') else None,
                            "Links": json.dumps(fields.get('issuelinks')) if fields.get('issuelinks') else None,
                            "Date_ordered": fields.get('customfield_13681') if fields.get('customfield_13681') else None,
                            "SLA_Ongoing_StartTime_jira": fields.get('customfield_20325', {}).get('ongoingCycle',{}).get('startTime', {}).get('jira') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle',{}).get('startTime') else None,
                            "SLA_Ongoing_BreachTime_jira": fields.get('customfield_20325', {}).get('ongoingCycle',{}).get('breachTime', {}).get('jira') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle',{}).get('breachTime') else None,
                            "SLA_Ongoing_Breached": fields.get('customfield_20325', {}).get('ongoingCycle',{}).get('breached') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle') else None,
                            "SLA_Ongoing_elapsedTime_millis": fields.get('customfield_20325', {}).get('ongoingCycle',{}).get('elapsedTime', {}).get('millis') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle',{}).get('elapsedTime') else None,
                            "SLA_Ongoing_remainingTime_millis": fields.get('customfield_20325', {}).get('ongoingCycle',{}).get('remainingTime', {}).get('millis') if fields.get('customfield_20325') and fields.get('customfield_20325').get('ongoingCycle',{}).get('remainingTime') else None,
                        })

                        if len(rows_to_insert) >= CHUNK_SIZE:
                            insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert)
                            rows_to_insert = []

                    except Exception as e:
                        logging.exception(f"Error processing issue {issue.get('key')}: {e}")

                start_at += max_results  # Increment start_at to fetch the next batch of issues

            except requests.RequestException as e:
                logging.error(f"Error fetching data from Jira: {e}")
                break

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery")
            insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert)

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
        USING (
            SELECT
                ARRAY_AGG(S ORDER BY Updated DESC LIMIT 1)[OFFSET(0)] AS row
            FROM `{dataset_id}.{temp_table_id}` S
            GROUP BY Key
        ) S
        ON T.Key = S.row.Key
        WHEN MATCHED THEN
            UPDATE SET
                T.Type = S.row.Type,
                T.Priority = S.row.Priority,
                T.Summary = S.row.Summary,
                T.Status = S.row.Status,
                T.Created = S.row.Created,
                T.Updated = S.row.Updated,
                T.Resolved = S.row.Resolved,
                T.Assignee = S.row.Assignee,
                T.Task_Definition = S.row.Task_Definition,
                T.Console_Service = S.row.Console_Service,
                T.Port_Prov_Status = S.row.Port_Prov_Status,
                T.Remedy_Ticket_Number = S.row.Remedy_Ticket_Number,
                T.Creator = S.row.Creator,
                T.Components = S.row.Components,
                T.Labels = S.row.Labels,
                T.Handover_Instruction = S.row.Handover_Instruction,
                T.Handover_Report_AS = S.row.Handover_Report_AS,
                T.Resolution = S.row.Resolution,
                T.Resolution_Time = S.row.Resolution_Time,
                T.First_Response = S.row.First_Response,
                T.Reporter = S.row.Reporter,
                T.Request_Type = S.row.Request_Type,
                T.Links = S.row.Links,
                T.Date_ordered = S.row.Date_ordered,
                T.SLA_Ongoing_StartTime_jira = S.row.SLA_Ongoing_StartTime_jira,
                T.SLA_Ongoing_BreachTime_jira = S.row.SLA_Ongoing_BreachTime_jira,
                T.SLA_Ongoing_Breached = S.row.SLA_Ongoing_Breached,
                T.SLA_Ongoing_elapsedTime_millis = S.row.SLA_Ongoing_elapsedTime_millis,
                T.SLA_Ongoing_remainingTime_millis = S.row.SLA_Ongoing_remainingTime_millis
        WHEN NOT MATCHED THEN
            INSERT (Type, Priority, Key, Summary, Status, Created, Updated, Resolved, Assignee, Task_Definition, Console_Service, Port_Prov_Status, Remedy_Ticket_Number, Creator, Components, Labels, Handover_Instruction, Handover_Report_AS, Resolution, Resolution_Time, First_Response, Reporter, Request_Type, Links, Date_ordered, SLA_Ongoing_StartTime_jira, SLA_Ongoing_BreachTime_jira, SLA_Ongoing_Breached, SLA_Ongoing_elapsedTime_millis, SLA_Ongoing_remainingTime_millis)
            VALUES(S.row.Type, S.row.Priority, S.row.Key, S.row.Summary, S.row.Status, S.row.Created, S.row.Updated, S.row.Resolved, S.row.Assignee, S.row.Task_Definition, S.row.Console_Service, S.row.Port_Prov_Status, S.row.Remedy_Ticket_Number, S.row.Creator, S.row.Components, S.row.Labels, S.row.Handover_Instruction, S.row.Handover_Report_AS, S.row.Resolution, S.row.Resolution_Time, S.row.First_Response, S.row.Reporter, S.row.Request_Type, S.row.Links, S.row.Date_ordered, S.row.SLA_Ongoing_StartTime_jira, S.row.SLA_Ongoing_BreachTime_jira, S.row.SLA_Ongoing_Breached, S.row.SLA_Ongoing_elapsedTime_millis, S.row.SLA_Ongoing_remainingTime_millis)
        """
        client.query(merge_query).result()
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