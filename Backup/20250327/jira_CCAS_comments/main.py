import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os

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
    try:
        client.query(f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(f'{f.name} {f.field_type}' for f in schema)})").result()
        logging.info(f"Temporary table '{dataset_id}.{table_id}' created or replaced.")
        return True 
    except Exception as e:
        logging.exception(f"Error creating or replacing temporary table '{dataset_id}.{table_id}': {e}")
        return False 

def delete_temp_table(client, dataset_id, table_id):
    table_ref = client.dataset(dataset_id).table(table_id)
    try:
        client.delete_table(table_ref)
        logging.info(f"Temporary table '{dataset_id}.{table_id}' deleted.")
        return True
    except Exception as e:
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False

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

def fetch_comments_for_issue(jira_url, issue_key, username, api_token, max_results=50):
    """Fetches all comments for a given issue, handling pagination."""
    all_comments = []
    start_at = 0

    while True:
        url = f"{jira_url}/rest/api/2/issue/{issue_key}/comment"
        headers = {"Accept": "application/json"}
        auth = (username, api_token)
        params = {"startAt": start_at, "maxResults": max_results}

        try:
            response = requests.get(url, headers=headers, auth=auth, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            comments = data.get('comments', [])
            all_comments.extend(comments)

            total_comments = data.get('total', 0)
            if start_at + max_results >= total_comments:
                break  

            start_at += max_results

        except requests.RequestException as e:
            logging.error(f"Error fetching comments for issue {issue_key}: {e}")
            return None  
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for issue {issue_key}: {e}")
            return None

    return all_comments 


def sync_comments_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client): #adjusted the sync comment to only accept one page of issues
    
    temp_table_id = f"{table_id}_temp" 

    schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Comment_ID", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Author_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Author_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Body", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Value", "STRING", mode="NULLABLE"),
    ]

    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, schema):
        logging.error("Failed to create or replace temporary table.")
        return False 

    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error(f"Temporary table '{dataset_id}.{temp_table_id}' is not available.")
        return False

    total_issues = float('inf')  
    start_at = 0
    max_results = 50 
    issues_processed = 0
    batch_size = 500

    while start_at < total_issues:

        url = f"{jira_url}/rest/api/2/search"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (username, api_token)
        payload = json.dumps({"jql": jql_query, "startAt": start_at, "maxResults": max_results})

        try:
            response = requests.post(url, headers=headers, auth=auth, data=payload, timeout=120)
            response.raise_for_status()

            data = response.json()
            issues = data.get('issues', [])
            total_issues = data.get('total', 0) 

            if not issues:
                logging.info("No issues found on this page.")
                break 

            rows_to_insert = [] 
            for issue in issues:
                issue_key = issue.get('key')
                if not issue_key:
                    logging.warning(f"Issue missing key. Skipping.")
                    continue

                comments = fetch_comments_for_issue(jira_url, issue_key, username, api_token)

                if comments is None:
                    logging.error(f"Could not retrieve comments for {issue_key}.  Skipping.")
                    continue  

                for comment in comments:
                    try:
                        rows_to_insert.append({
                            "Issue_Key": issue_key,
                            "Comment_ID": comment.get('id'),
                            "Author_Account_ID": comment.get('author', {}).get('accountId'),
                            "Author_Display_Name": comment.get('author', {}).get('displayName'),
                            "Created": convert_timestamp(comment.get('created')),
                            "Updated": convert_timestamp(comment.get('updated')),
                            "Body": comment.get('body'),
                            "Visibility_Type": comment.get('visibility', {}).get('type'),
                            "Visibility_Value": comment.get('visibility', {}).get('value'),
                        })
                    except Exception as e:
                        logging.exception(f"Error processing comment {comment.get('id')} for issue {issue_key}: {e}")

                    if len(rows_to_insert) >= batch_size:
                        if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert):
                            logging.error(f"Failed to insert batch of {batch_size} rows.  Stopping processing.")
            
                            return False
                        rows_to_insert = []

            if rows_to_insert:
                insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert)

            start_at += max_results  
            issues_processed += len(issues) 
            logging.info(f"Processed {len(issues)} issues. Total issues processed: {issues_processed}")

        except requests.RequestException as e:
            logging.error(f"Error searching issues: {e}")
            return False 
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for search issues: {e}")
            return False 

    #MERGE
    merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING `{dataset_id}.{temp_table_id}` S
        ON T.Comment_ID = S.Comment_ID
        WHEN MATCHED THEN
            UPDATE SET
                T.Issue_Key = S.Issue_Key,
                T.Author_Account_ID = S.Author_Account_ID,
                T.Author_Display_Name = S.Author_Display_Name,
                T.Created = S.Created,
                T.Updated = S.Updated,
                T.Body = S.Body,
                T.Visibility_Type = S.Visibility_Type,
                T.Visibility_Value = S.Visibility_Value
        WHEN NOT MATCHED THEN
            INSERT (Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body, Visibility_Type, Visibility_Value)
            VALUES (S.Issue_Key, S.Comment_ID, S.Author_Account_ID, S.Author_Display_Name, S.Created, S.Updated, S.Body, S.Visibility_Type, S.Visibility_Value)
    """

    try:
        client.query(merge_query).result()
        logging.info("Data merged successfully.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        return False

    
    if not delete_temp_table(client, dataset_id, temp_table_id):
        logging.error("Failed to delete temporary table.")
        return False

    return True 

def main():
    config = load_config()
    if config is None:
        return None

    jira_url = 'https://jira.pccwglobal.com'  
    jql_query = 'filter=26447'  
    username = 'jjkli'  
    api_token = config.get('jira_api_token') 

    dataset_id = 'JIRA'  
    table_id = 'CCAS_comments'  

    client = bigquery.Client()

    if sync_comments_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client):
        logging.info("Successfully synced comments to BigQuery.")
    else:
        logging.error("Failed to sync comments to BigQuery.")
    return None 

if __name__ == "__main__":
    main()