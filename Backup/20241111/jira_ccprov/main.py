import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def create_or_truncate_table(client, dataset_id, table_id, schema):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        table = client.get_table(table_ref)
        logging.info(f"Table '{table_id}' found. Truncating...")
        client.query(f"TRUNCATE TABLE `{dataset_id}.{table_id}`").result()
        logging.info(f"Table '{table_id}' truncated successfully.")
    except Exception as e:
        logging.info(f"Table '{table_id}' not found. Creating...")
        table = bigquery.Table(table_ref, schema=schema)
        table = client.create_table(table)
        logging.info(f"Table '{table_id}' created successfully.")
        time.sleep(5)  # Allow time for table creation

def fetch_and_sync_jira_data():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://jira.pccwglobal.com/rest/api/2/search'
    jql_query = 'filter=25713'  # JQL filter for ccprov
    username = 'jjkli' #Your Jira username - replace this
    api_token = config.get('jira_api_token')
    start_at = 0
    max_results = 50
    batch_size = 100
    CHUNK_SIZE = 1000

    try:
        client = bigquery.Client()
        dataset_id = 'JIRA'
        table_id = 'project_CCPROV'
        temp_table_id = 'project_CCPROV_temp'

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
            bigquery.SchemaField("Port Prov Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("On-Board Checklist", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Onboard Category", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Insight ID", "STRING", mode="NULLABLE"),
        ]

        create_or_truncate_table(client, dataset_id, temp_table_id, schema)

        rows_to_insert = []
        while True:
            logging.info(f"Fetching data from Jira, startAt: {start_at}")
            try:
                response = requests.get(jira_url, auth=(username, api_token),
                                        params={'jql': jql_query, 'startAt': start_at, 'maxResults': max_results},
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

                    reporter_data = fields.get('reporter')
                    reporter = reporter_data.get('displayName') if reporter_data else None

                    assignee_data = fields.get('assignee')
                    assignee = assignee_data.get('displayName') if assignee_data else None

                    creator_data = fields.get('creator')
                    creator = creator_data.get('displayName') if creator_data else None


                    onboard_checklist_data = fields.get('customfield_17003', [])
                    onboard_checklist = ', '.join([item.get('value', 'N/A') for item in onboard_checklist_data]) if onboard_checklist_data else None

                    port_prov_status = fields.get('customfield_16605', {}).get('value')
                    onboard_category = fields.get('customfield_16593', {}).get('value')
                    insight_id = fields.get('customfield_16597')

                    row = {
                        'T': fields.get('issuetype', {}).get('name', 'N/A'),
                        'Project': fields.get('project', {}).get('name', 'N/A'),
                        'Key': issue.get('key', 'N/A'),
                        'Summary': fields.get('summary', 'N/A'),
                        'Status': fields.get('status', {}).get('name', 'N/A'),
                        'Created': convert_timestamp(fields.get('created')),
                        'Updated': convert_timestamp(fields.get('updated')),
                        'Resolved': convert_timestamp(fields.get('resolutiondate')),
                        'Reporter': reporter,
                        'Assignee': assignee,
                        'Creator': creator,
                        'Port Prov Status': port_prov_status,
                        'On-Board Checklist': onboard_checklist,
                        'Onboard Category': onboard_category,
                        'Insight ID': insight_id,
                    }
                    rows_to_insert.append(row)
                    if len(rows_to_insert) >= CHUNK_SIZE:
                        errors = client.insert_rows_json(client.dataset('JIRA').table('project_CCPROV_temp'), rows_to_insert)
                        if errors:
                            logging.error(f"Errors inserting rows: {errors}")
                            return
                        rows_to_insert = []

                start_at += max_results

            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching data from Jira: {e}")
                return

        if rows_to_insert:
            errors = client.insert_rows_json(client.dataset('JIRA').table('project_CCPROV_temp'), rows_to_insert)
            if errors:
                logging.error(f"Errors inserting rows: {errors}")
                return


        merge_query = f"""
        MERGE `{dataset_id}.{table_id}` AS target
        USING `{dataset_id}.{temp_table_id}` AS source
        ON target.Key = source.Key
        WHEN MATCHED THEN UPDATE SET target.Summary = source.Summary,
                                      target.Status = source.Status,
                                      target.Created = source.Created,
                                      target.Updated = source.Updated,
                                      target.Resolved = source.Resolved,
                                      target.Reporter = source.Reporter,
                                      target.Assignee = source.Assignee,
                                      target.Creator = source.Creator,
                                      target.`Port Prov Status` = source.`Port Prov Status`,
                                      target.`On-Board Checklist` = source.`On-Board Checklist`,
                                      target.`Onboard Category` = source.`Onboard Category`,
                                      target.`Insight ID` = source.`Insight ID`,
                                      target.Project = source.Project,
                                      target.T = source.T
        WHEN NOT MATCHED THEN INSERT ROW
        """
        logging.info(f"Running merge query: {merge_query}")
        client.query(merge_query).result()
        logging.info("Merge completed successfully.")

        client.delete_table(client.dataset('JIRA').table('project_CCPROV_temp'))
        logging.info("Temporary table deleted successfully.")

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")

if __name__ == '__main__':
    fetch_and_sync_jira_data()