import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os
from google.api_core.exceptions import Conflict, NotFound

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.Formatter.converter = time.localtime

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        return None
    except json.JSONDecodeError:
        logging.error("Error decoding config.json. Please ensure it's valid JSON.")
        return None

def convert_timestamp(timestamp):
    if timestamp:
        try:
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}. Trying without timezone info if applicable.")
                try:
                    return datetime.strptime(timestamp.split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    logging.error(f"Could not parse timestamp: {timestamp}")
                    return None
    return None

def get_field_value(field_data):
    if field_data is None:
        return None
    
    if isinstance(field_data, dict):
        if 'value' in field_data:
            return str(field_data['value'])
        if 'name' in field_data:
            return str(field_data['name'])
        if 'displayName' in field_data:
             return str(field_data['displayName'])
        logging.warning(f"Unhandled dictionary field structure: {field_data}. Returning raw string.")
        return str(field_data) 
    elif isinstance(field_data, list):
        values = []
        for item in field_data:
            if isinstance(item, dict):
                if 'value' in item:
                    values.append(str(item['value']))
                elif 'name' in item:
                    values.append(str(item['name']))
                else:
                    values.append(str(item))
            else:
                values.append(str(item))
        return ', '.join(values) if values else None
    elif isinstance(field_data, bool):
        return str(field_data)
    else:
        return str(field_data)

def create_temp_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.get_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' already exists. Deleting it.")
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
    except NotFound:
        logging.info(f"Temporary table '{dataset_id}.{table_id}' not found, will create a new one.")
    
    table = bigquery.Table(table_ref, schema=schema)
    try:
        client.create_table(table)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created.")
    except Conflict:
        logging.warning(f"Temporary table '{dataset_id}.{table_id}' creation conflict. It might have been created by a concurrent process.")

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted (or did not exist).")
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    jql_query = 'project = CCPROV AND IssueType != File.13 AND "Port Prov Status" != Cancelled AND updated >= endOfDay(-8) ORDER BY updated DESC'
    username = 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')

    if not api_token:
        logging.error("Jira API token not found in config.json. Please add it.")
        return

    start_at = 0
    max_results = 100
    CHUNK_SIZE = 500
    RETRY_COUNT = 3
    RETRY_DELAY = 10

    try:
        client = bigquery.Client()
        dataset_id = 'JIRAProjects'
        table_id = 'CCPROV'
        temp_table_id = 'CCPROV_temp'

        schema = [
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
            bigquery.SchemaField("Creator", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Port_Prov_Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("On_Board_Checklist", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Onboard_Category", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Insight_ID", "STRING", mode="NULLABLE"),
        ]

        create_temp_table(client, dataset_id, temp_table_id, schema)

        rows_to_insert = []
        total_issues_fetched = 0

        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            params = {
                'jql': jql_query,
                'startAt': start_at,
                'maxResults': max_results,
                'fields': (
                    'issuetype,project,summary,status,created,updated,resolutiondate,'
                    'reporter,assignee,creator,'
                    'customfield_10000,'
                    'customfield_10001,'
                    'customfield_10002,'
                    'customfield_10003'
                ),
                'expand': 'names'
            }
            
            response = None
            data = None
            for attempt in range(RETRY_COUNT):
                try:
                    response = requests.get(jira_url, auth=(username, api_token),
                                            params=params, timeout=300)
                    response.raise_for_status()
                    data = response.json()
                    break
                except requests.exceptions.RequestException as e:
                    logging.error(f"Jira request failed (attempt {attempt+1}/{RETRY_COUNT}): {e}")
                    if attempt + 1 == RETRY_COUNT:
                        logging.error("Max retries reached for Jira API request. Aborting.")
                        delete_temp_table(client, dataset_id, temp_table_id)
                        return
                    time.sleep(RETRY_DELAY * (attempt + 1))
            
            if response is None or data is None:
                logging.error("Failed to fetch data from Jira after retries.")
                delete_temp_table(client, dataset_id, temp_table_id)
                return

            issues = data.get('issues', [])
            if not issues:
                logging.info("No more issues returned from Jira.")
                break
            
            total_issues_fetched += len(issues)
            logging.info(f"Fetched {len(issues)} issues in this batch. Total fetched so far: {total_issues_fetched}")

            for issue in issues:
                fields = issue.get('fields')
                if fields is None:
                    logging.warning(f"Issue {issue.get('key', 'N/A')} is missing 'fields' key. Skipping...")
                    continue
                
                issuetype_name = get_field_value(fields.get('issuetype'))
                project_name = get_field_value(fields.get('project'))
                status_name = get_field_value(fields.get('status'))
                reporter_name = get_field_value(fields.get('reporter'))
                assignee_name = get_field_value(fields.get('assignee'))
                creator_name = get_field_value(fields.get('creator'))

                row = {
                    'T': issuetype_name,
                    'Project': project_name,
                    'Key': issue.get('key'),
                    'Summary': fields.get('summary'),
                    'Status': status_name,
                    'Created': convert_timestamp(fields.get('created')),
                    'Updated': convert_timestamp(fields.get('updated')),
                    'Resolved': convert_timestamp(fields.get('resolutiondate')),
                    'Reporter': reporter_name,
                    'Assignee': assignee_name,
                    'Creator': creator_name,
                    'Port_Prov_Status': get_field_value(fields.get('customfield_10000')),
                    'On_Board_Checklist': get_field_value(fields.get('customfield_10001')),
                    'Onboard_Category': get_field_value(fields.get('customfield_10002')),
                    'Insight_ID': get_field_value(fields.get('customfield_10003'))
                }
                if not row['Key']:
                    logging.warning(f"Issue data missing 'Key'. Skipping row: {row}")
                    continue
                
                rows_to_insert.append(row)

                if len(rows_to_insert) >= CHUNK_SIZE:
                    logging.info(f"Inserting {len(rows_to_insert)} rows into BigQuery temp table.")
                    errors = client.insert_rows_json(f"{dataset_id}.{temp_table_id}", rows_to_insert)
                    if errors:
                        logging.error(f"Errors inserting rows into BigQuery temp table: {errors}")
                        delete_temp_table(client, dataset_id, temp_table_id)
                        return
                    rows_to_insert = []
            
            if data.get('total', 0) <= start_at + len(issues):
                logging.info("All issues fetched according to Jira's 'total' count.")
                break
            start_at += len(issues)

        if rows_to_insert:
            logging.info(f"Inserting remaining {len(rows_to_insert)} rows into BigQuery temp table.")
            errors = client.insert_rows_json(f"{dataset_id}.{temp_table_id}", rows_to_insert)
            if errors:
                logging.error(f"Errors inserting remaining rows into BigQuery temp table: {errors}")
                delete_temp_table(client, dataset_id, temp_table_id)
                return
        
        logging.info(f"Total issues processed and attempted to insert: {total_issues_fetched}")

        query_job = client.query(f"SELECT COUNT(*) as count FROM `{dataset_id}.{temp_table_id}`")
        results = query_job.result()
        count_in_temp = 0
        for r in results:
            count_in_temp = r.count
        logging.info(f"Count of rows in temporary table '{temp_table_id}': {count_in_temp}")

        if count_in_temp == 0 and total_issues_fetched > 0:
            logging.warning("No rows were inserted into the temporary table, but issues were fetched. Check for data processing errors or all issues being skipped.")

        merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING `{dataset_id}.{temp_table_id}` S
        ON T.Key = S.Key
        WHEN MATCHED THEN
            UPDATE SET
                T.T = S.T,
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
            INSERT (T, Project, Key, Summary, Status, Created, Updated, Resolved, Reporter, Assignee, Creator, 
                    `Port Prov Status`, `On-Board Checklist`, `Onboard Category`, `Insight ID`)
            VALUES (S.T, S.Project, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, S.Creator, 
                    S.Port_Prov_Status, S.On_Board_Checklist, S.Onboard_Category, S.Insight_ID)
        """
        logging.info("Executing MERGE statement...")
        try:
            merge_job = client.query(merge_query)
            merge_job.result()
            logging.info(f"Data merged successfully into '{dataset_id}.{table_id}'. Rows affected: {merge_job.num_dml_affected_rows}")
        except Exception as e:
            logging.exception(f"Error during MERGE operation: {e}")
            return 

        logging.info("Verifying merge result...")
        verify_query = f"SELECT COUNT(*) as row_count FROM `{dataset_id}.{table_id}`"
        verify_job = client.query(verify_query)
        for row in verify_job.result():
            logging.info(f"Row count in target table after merge: {row['row_count']}")

    except NotFound as e:
        logging.error(f"BigQuery resource not found: {e}. Ensure dataset '{dataset_id}' and table '{table_id}' exist or permissions are correct.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
    finally:
        if 'client' in locals() and 'dataset_id' in locals() and 'temp_table_id' in locals():
             delete_temp_table(client, dataset_id, temp_table_id)
        else:
            logging.info("Skipping temp table deletion as client/table IDs might not be initialized due to an early error.")

def main():
    fetch_and_sync_jira_data()

if __name__ == "__main__":
    main()