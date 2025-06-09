import requests
import json
from google.cloud import bigquery
import logging
from datetime import datetime
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Define DEBUG flag before logging setup
DEBUG = False

# Setup logging (reduce verbosity unless DEBUG=True)
logging.basicConfig(level=logging.INFO if not DEBUG else logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
            # Adjust format string to handle potential lack of milliseconds
            # Also, ensure timezone offset is handled correctly (e.g., '+0000' or 'Z')
            # Jira Cloud often returns 'Z' for UTC
            if timestamp.endswith('Z'):
                 return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%d %H:%M:%S')
            else: # Try with milliseconds and timezone offset
                 return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            logging.warning(f"Invalid timestamp format: {timestamp}, Error: {e}")
            # Attempt to parse without milliseconds if the above fails
            try:
                if timestamp.endswith('Z'):
                     return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')
                else:
                     return datetime.strptime(timestamp.rsplit('.', 1)[0] + timestamp.rsplit('.', 1)[1][3:], '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e2:
                logging.warning(f"Could not parse timestamp after retry: {timestamp}, Error: {e2}")
                return None
    return None


def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        # Use standard SQL for CREATE OR REPLACE
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(f'`{f.name}` {f.field_type}' for f in schema)})"
        logging.debug(f"Executing query: {query}")
        client.query(query).result()
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
        # Handle case where table might not exist (e.g., script failed early)
        if 'Not found' in str(e):
             logging.warning(f"Temporary table '{dataset_id}.{table_id}' not found during deletion attempt, likely already gone or never created.")
             return True # Treat as successful deletion if not found
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception as e:
        # BigQuery client raises a NotFound exception if the table doesn't exist
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
            # Use the table reference directly for insertion
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into '{dataset_id}.{table_id}'.")
                return True
            logging.error(f"Errors occurred while inserting rows: {errors}")
        except Exception as e:
            # Explicitly check for 'Not found' error which indicates the table is missing/truncated
            if "Not found" in str(e) or "Table is truncated" in str(e):
                 logging.warning(f"Table '{dataset_id}.{table_id}' not found or truncated during insert. Recreating...")
                 if create_or_replace_temp_table(client, dataset_id, table_id, schema) and wait_for_table(client, dataset_id, table_id):
                     logging.info("Table recreated successfully, retrying insert.")
                     continue # Retry the insert immediately after recreation
                 else:
                     logging.error("Failed to recreate table or wait for it to become available. Cannot retry insert.")
                     return False # Cannot proceed if recreation fails
            else:
                logging.exception(f"Error inserting rows into BigQuery (Attempt {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            logging.info(f"Retrying insert rows into '{dataset_id}.{table_id}'. Attempt {attempt + 2}/{retries}")
            time.sleep(delay)
        else:
            logging.error(f"Failed to insert rows after {retries} attempts.")
            return False
    return False # Should be unreachable if retries Exhausted, but good practice

# Use /rest/api/2 for comments as it's generally compatible
def fetch_comments_for_issue(jira_base_url, issue_key, username, api_token, max_results=75):
    all_comments = []
    start_at = 0

    while True:
        # Construct the full URL using the base URL and the /rest/api/2 path
        url = f"{jira_base_url}/rest/api/2/issue/{issue_key}/comment"
        headers = {"Accept": "application/json"}
        # Basic Auth with username and API token
        auth = (username, api_token)
        params = {"startAt": start_at, "maxResults": max_results}

        logging.debug(f"Fetching comments for {issue_key} starting at {start_at}")

        try:
            # Add a timeout for the request
            response = requests.get(url, headers=headers, auth=auth, params=params, timeout=120)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            data = response.json()
            comments = data.get('comments', [])
            all_comments.extend(comments)

            total_comments = data.get('total', 0)
            if start_at + len(comments) >= total_comments: # Check if we got all comments on this page or exceeded total
                 break # Exit the loop if all comments are fetched

            start_at += len(comments) # Use actual number of comments returned in case max_results is ignored/capped


        except requests.RequestException as e:
            # Log specific error details, including response text if available
            error_message = f"Error fetching comments for issue {issue_key}: {e}"
            if e.response is not None:
                 error_message += f", Status Code: {e.response.status_code}, Response Text: {e.response.text}"
            logging.error(error_message)
            return None # Return None to indicate failure for this issue

        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for comments of issue {issue_key}: {e}")
            return None # Return None to indicate failure

    logging.debug(f"Fetched {len(all_comments)} comments for issue {issue_key}")
    return all_comments

def fetch_comments_batch(jira_base_url, issue_keys, username, api_token, max_results=75):
    # Pass the base URL to the worker function
    def fetch_single_issue(key):
        return key, fetch_comments_for_issue(jira_base_url, key, username, api_token, max_results)

    results = {}
    # Use a reasonable number of workers, adjust based on your environment and Jira Cloud rate limits
    MAX_CONCURRENT_COMMENT_FETCHES = 16 # Increased from 8, can be tuned
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COMMENT_FETCHES) as executor:
        # Use a dictionary comprehension for cleaner submission
        future_to_key = {executor.submit(fetch_single_issue, key): key for key in issue_keys}
        
        for future in as_completed(future_to_key):
            issue_key = future_to_key[future]
            try:
                key, comments = future.result()
                results[key] = comments
                # Add a small delay between requests to potentially help with rate limits
                time.sleep(0.1) 
            except Exception as exc:
                logging.error(f'{issue_key} generated an exception: {exc}')
                results[issue_key] = None # Indicate failure for this specific issue

    return results

def generate_rows(issues, jira_base_url, username, api_token):
    # Ensure issue_keys only contains valid keys
    issue_keys = [issue.get('key') for issue in issues if issue and issue.get('key')]
    if not issue_keys:
        logging.warning("No valid issue keys provided to generate_rows.")
        return # Generator yields nothing

    # Pass the base URL to the batch fetch function
    comments_batch = fetch_comments_batch(jira_base_url, issue_keys, username, api_token)

    for issue_key in issue_keys: # Iterate through the original issue keys list
        comments = comments_batch.get(issue_key)
        if comments is None:
            # Error was already logged in fetch_comments_batch or fetch_comments_for_issue
            # logging.error(f"Could not retrieve comments for {issue_key}. Skipping.") # Avoid double logging
            continue
        if not comments:
             logging.debug(f"No comments found for issue {issue_key}.")
             continue # Skip if the issue has no comments

        for comment in comments:
            try:
                # Ensure comment ID exists as it's a required field in schema
                comment_id = comment.get('id')
                if not comment_id:
                     logging.warning(f"Skipping comment with no ID for issue {issue_key}: {comment}")
                     continue

                # Safely get nested fields
                author_info = comment.get('author', {})
                visibility_info = comment.get('visibility', {})

                yield {
                    "Issue_Key": issue_key,
                    "Comment_ID": comment_id,
                    "Author_Account_ID": author_info.get('accountId'),
                    "Author_Display_Name": author_info.get('displayName'),
                    "Created": convert_timestamp(comment.get('created')),
                    "Updated": convert_timestamp(comment.get('updated')),
                    "Body": comment.get('body'),
                    "Visibility_Type": visibility_info.get('type'),
                    "Visibility_Value": visibility_info.get('value'),
                }
            except Exception as e:
                logging.exception(f"Error processing comment {comment.get('id')} for issue {issue_key}: {e}")


# Pass the base URL and the new JQL query
def sync_comments_to_bigquery(jira_base_url, jql_query, username, api_token, dataset_id, table_id, client):
    # Create a unique temporary table name
    temp_table_id = f"{table_id}_temp_{int(time.time())}"

    schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Comment_ID", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Author_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Author_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Body", "STRING", mode="NULLABLE"), # Jira comment body can be large
        bigquery.SchemaField("Visibility_Type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Value", "STRING", mode="NULLABLE"),
    ]
    
    # Ensure STRING fields that might hold large text are handled
    # BigQuery STRING max size is 2MB. If bodies are larger, consider BYTES or checking size.
    # For typical comments, STRING is fine.

    logging.info(f"Syncing comments using JQL: {jql_query}")

    # --- Temporary Table Creation ---
    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, schema):
        logging.error("Setup failed: Could not create or replace temporary table.")
        return False

    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error("Setup failed: Temporary table not available.")
        # Attempt to clean up the potentially failed table creation
        delete_temp_table(client, dataset_id, temp_table_id) 
        return False

    # --- Jira Search and Data Extraction ---
    total_issues = float('inf')
    start_at = 0
    max_results = 50 # Max results for JQL search, can be up to 100 in Jira Cloud
    issues_processed = 0
    # Batch size for inserting rows into BigQuery - keep it reasonable
    batch_size = 1000 
    total_rows_inserted_to_temp = 0

    # Construct the full search URL using the base URL and the /rest/api/2 path
    # Although user mentioned '/latest', /rest/api/2/search is also valid and consistent
    # with the comments endpoint path used in the script.
    search_url = f"{jira_base_url}/rest/api/2/search" 
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)

    logging.info(f"Starting Jira search from {search_url}")

    while start_at < total_issues:
        # The payload now includes the direct 'jql' string
        payload = json.dumps({
            "jql": jql_query,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["key"] # Only need the issue key for fetching comments
        })

        logging.info(f"Fetching issues with JQL, startAt: {start_at}, maxResults: {max_results}")

        # --- Jira Search API Call with Retries ---
        response = None # Define response before the loop
        for attempt in range(5): # Increased retries for network issues
            try:
                # Add a generous timeout for the search request as it might be slow
                response = requests.post(search_url, headers=headers, auth=auth, data=payload, timeout=300) 
                response.raise_for_status()
                break # Success, exit retry loop
            except requests.exceptions.Timeout:
                 logging.warning(f"Search request timed out on attempt {attempt + 1}/5. Retrying...")
                 time.sleep(15) # Wait longer on timeout
            except requests.RequestException as e:
                error_message = f"Error searching issues on attempt {attempt + 1}/5: {e}"
                if e.response is not None:
                    error_message += f", Status Code: {e.response.status_code}, Response Text: {e.response.text}"
                    # Handle specific Jira Cloud rate limiting (429)
                    if e.response.status_code == 429:
                         retry_after = e.response.headers.get('Retry-After', 30) # Default 30 seconds
                         logging.warning(f"Rate limited (429). Retrying after {retry_after} seconds...")
                         time.sleep(int(retry_after))
                         continue # Skip sleep below, retry immediately after waiting
                logging.error(error_message)

                if attempt < 4:
                    logging.info(f"Retrying Jira search in 10 seconds...")
                    time.sleep(10)
                else:
                    logging.error("Failed to search issues after multiple attempts.")
                    delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                    return False # Give up after retries

        if response is None: # If loop finished without a successful response
             logging.error("Jira search failed after multiple retries.")
             delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table
             return False

        # --- Process Search Results ---
        try:
            data = response.json()
            issues = data.get('issues', [])
            total_issues = data.get('total', 0) # Get the *total* number of issues matching the JQL

            if not issues:
                logging.info(f"No issues found on this page (startAt: {start_at}). Total issues reported: {total_issues}.")
                if start_at == 0 and total_issues > 0:
                    # This might happen if maxResults is too large or pagination is odd
                    logging.warning("Got 0 issues on first page but total > 0. Check maxResults or JQL.")
                break # No more issues to process

            logging.info(f"Fetched {len(issues)} issues (startAt: {start_at}) out of total {total_issues}")

            rows_to_insert = []
            # Pass the base URL to generate_rows
            for row in generate_rows(issues, jira_base_url, username, api_token):
                rows_to_insert.append(row)
                if len(rows_to_insert) >= batch_size:
                    if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, schema):
                        logging.error(f"Failed to insert batch of {len(rows_to_insert)} rows into temp table. Stopping processing.")
                        delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                        return False
                    total_rows_inserted_to_temp += len(rows_to_insert)
                    rows_to_insert = []

            # Insert any remaining rows in the last batch
            if rows_to_insert:
                if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, schema):
                    logging.error(f"Failed to insert remaining {len(rows_to_insert)} rows into temp table. Stopping processing.")
                    delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
                    return False
                total_rows_inserted_to_temp += len(rows_to_insert)


            start_at += len(issues) # Increment start_at by the number of issues *actually* returned
            issues_processed += len(issues)
            logging.info(f"Finished processing {len(issues)} issues from this page. Total issues processed so far: {issues_processed}/{total_issues}")

            # Optional: Add a short delay between search pages to be nice to Jira API
            time.sleep(1)

        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response for search issues: {e}. Response text: {response.text if response else 'N/A'}")
            delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
            return False
        except Exception as e:
            logging.exception(f"An unexpected error occurred during issue processing: {e}")
            delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
            return False


    logging.info(f"Finished fetching and inserting data into temporary table '{temp_table_id}'. Total rows inserted: {total_rows_inserted_to_temp}")

    # --- Merge Data into Final Table ---
    logging.info(f"Starting merge operation from '{temp_table_id}' to '{table_id}'...")
    merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING `{dataset_id}.{temp_table_id}` S
        ON T.Comment_ID = S.Comment_ID
        WHEN MATCHED THEN
            -- Only update if relevant fields have changed
            -- Note: Check for changes in all fields except the join key if you want a full sync
            -- Comparing timestamps directly might be an issue if precision differs
            -- Comparing stringified timestamps or using checksums/hashes is more robust
            -- For simplicity, let's check key fields that are likely to change
            UPDATE SET
                T.Issue_Key = S.Issue_Key, -- Should not change for an existing comment ID
                T.Author_Account_ID = S.Author_Account_ID,
                T.Author_Display_Name = S.Author_Display_Name,
                -- Use COALESCE or IS DISTINCT FROM for NULL handling in comparison
                T.Created = S.Created,
                T.Updated = S.Updated,
                T.Body = S.Body,
                T.Visibility_Type = S.Visibility_Type,
                T.Visibility_Value = S.Visibility_Value
        WHEN NOT MATCHED THEN
            INSERT (Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body, Visibility_Type, Visibility_Value)
            VALUES (S.Issue_Key, S.Comment_ID, S.Author_Account_ID, S.Author_Display_Name, S.Created, S.Updated, S.Body, S.Visibility_Type, S.Visibility_Value)
    """
    # Note on MERGE WHEN MATCHED condition: BigQuery's MERGE requires a WHEN MATCHED clause even if no updates are intended.
    # The provided query updates all fields. If you only want to update if changes occurred,
    # you'd need a more complex `WHEN MATCHED AND (...)` condition comparing old and new values.
    # The current query effectively overwrites the existing row with the new data from the temp table.

    try:
        # Run the merge query
        query_job = client.query(merge_query)
        query_job.result() # Wait for the query to complete
        logging.info("Data merged successfully into final table.")
    except Exception as e:
        logging.exception(f"Error running merge query: {e}")
        delete_temp_table(client, dataset_id, temp_table_id) # Clean up temp table on failure
        return False
    finally:
         # --- Temporary Table Deletion ---
         # Ensure temp table is deleted even if merge fails, unless debugging is needed
         # You might want to keep it for debugging failed merges
         if not DEBUG: # Only delete if not in DEBUG mode
             if not delete_temp_table(client, dataset_id, temp_table_id):
                 logging.error("Failed to delete temporary table after merge.")
                 # Return True here? The merge succeeded, but cleanup failed.
                 # Decided to return False as part of the overall process failed.
                 return False
         else:
             logging.info(f"DEBUG mode is ON. Temporary table '{temp_table_id}' is kept for inspection.")


    logging.info(f"Sync process completed for JQL: {jql_query}")
    return True

def main():
    config = load_config()
    if config is None:
        # Error already logged in load_config
        return

    # --- UPDATED VALUES ---
    # Changed to the new Jira Cloud base URL
    jira_url = 'https://consoleconnect.atlassian.net'
    # Changed to the direct JQL query provided
    jql_query = 'project = "CCAS" AND updated >= endOfDay(-3) order by updated ASC'
    # -----------------------

    # Assuming username and API token key in config remain the same
    username = "jjkli@consoleconnect.com" # Get username from config
    api_token = config.get('jira_api_token')

    # Validate config values
    if not username:
        logging.error("Jira username is not configured in config.json.")
        return
    if not api_token:
        logging.error("Jira API token is not configured in config.json.")
        return


    dataset_id = 'JIRAProjects' # Assuming this remains the same
    table_id = 'CCAS_comments' # Assuming this remains the same

    try:
        client = bigquery.Client()
    except Exception as e:
         logging.exception(f"Failed to initialize BigQuery client: {e}. Ensure GCP credentials are set up correctly.")
         return


    # Pass the new jira_url and jql_query to the sync function
    if sync_comments_to_bigquery(jira_url, jql_query, username, api_token, dataset_id, table_id, client):
        logging.info("Successfully synced comments to BigQuery.")
    else:
        logging.error("Failed to sync comments to BigQuery.")


if __name__ == "__main__":
    main()