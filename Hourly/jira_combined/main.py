import argparse
import logging
import time
import json
import requests
import uuid
from datetime import datetime
from google.cloud import bigquery
from bq_logger import log_to_bigquery

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.Formatter.converter = time.localtime

def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("config.json not found. Please create it with your Jira API token.")
        return None


# --- Utility Functions ---
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

def create_or_replace_temp_table(client, dataset_id, table_id, schema):
    try:
        def field_sql(f):
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
            return sql
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` ({', '.join(field_sql(f) for f in schema)})"
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
        if 'Not found' in str(e):
            logging.warning(f"Temporary table '{dataset_id}.{table_id}' not found during deletion attempt, likely already gone or never created.")
            return True
        logging.exception(f"Error deleting temporary table '{dataset_id}.{table_id}': {e}")
        return False

def convert_timestamp(timestamp):
    if timestamp:
        try:
            return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                logging.warning(f"Invalid timestamp format, cannot parse: {timestamp}, Error: {e}")
                return None
    return None

def get_field_value(field):
    if field is None:
        return None
    elif isinstance(field, dict):
        return field.get('value') or field.get('name') or field.get('displayName')
    elif isinstance(field, list):
        return ', '.join([str(item.get('value') or item.get('name') or item.get('displayName') if isinstance(item, dict) else item) for item in field])
    elif isinstance(field, bool):
        return str(field)
    else:
        return str(field)

def extract_issue_links(issuelinks):
    if not issuelinks or not isinstance(issuelinks, list):
        return None
    links = []
    def get_status(issue):
        if not issue:
            return None
        fields = issue.get('fields', {})
        status = fields.get('status', {})
        return status.get('name')
    for link in issuelinks:
        outward = link.get('outwardIssue')
        inward = link.get('inwardIssue')
        if outward:
            key = outward.get('key')
            status = get_status(outward)
            if key:
                if status:
                    links.append(f"{key} [{status}]")
                else:
                    links.append(f"{key}")
        if inward:
            key = inward.get('key')
            status = get_status(inward)
            if key:
                if status:
                    links.append(f"{key} [{status}]")
                else:
                    links.append(f"{key}")
    return ', '.join(links) if links else None

# --- Tickets Sync Logic ---
def sync_tickets(config, client, dataset_id, run_id):
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jira_url = 'https://consoleconnect.atlassian.net/rest/api/latest/search'
    username = 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')
    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    pipeline_name = "jira_tickets"
    SR_REF_JIRA_ID = 'customfield_10382'
    SR_REF_BQ_NAME = 'SR_Ref'
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
    # Shared JQL for all modes
    jql_query = (
        '('
        'project = "GS&O Data Analytics" OR '
        'project = "GS&O Tool Automation" OR '
        'project = "GS&O Knowledge Consolidation" OR '
        'project = "Google Contact Center AI Solution" OR '
        'project = TAC OR '
        'project = CCAS OR '
        'project = VOICECE OR '
        'project = IOTCE OR '
        'project = TXCE OR '
        'project = SMSCE OR '
        'project = MSS OR '
        'project = "Console Application Support" OR '
        'project = "Console Connect Provisioning" OR '
        'project = "Global Service Delivery Team" OR '
        'project = "Transmission TX-CE" OR '
        'project = "Mobility SMS - CE" OR '
        'project = "Managed Security Services"'
        ') AND updated >= -3h'
    )
    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
        logging.error("Setup failed: Could not create temp table.")
        return
    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error("Setup failed: Temp table not available.")
        return
    rows_to_insert = []
    total_issues = float('inf')
    start_at = 0
    max_results = 100
    def extract_sla_metrics(sla_field):
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
                "Links": extract_issue_links(fields.get('issuelinks')),
                SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
                "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
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
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_key = {executor.submit(fetch_issue_detail, key): key for key in issue_keys}
                for future in as_completed(future_to_key):
                    row = future.result()
                    if row:
                        rows_to_insert.append(row)
            start_at += len(issues)
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
    try:
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
    delete_temp_table(client, dataset_id, temp_table_id)

# --- Comments Sync Logic ---
def sync_comments(config, client, dataset_id, run_id):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jira_base_url = 'https://consoleconnect.atlassian.net'
    username = 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')
    table_id = 'JiraComments'
    temp_table_id = 'JiraComments_temp'
    pipeline_name = "jira_comments"
    bq_schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Comment_ID", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("Author_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Author_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Body", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Visibility_Value", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("InsertedAt", "TIMESTAMP", mode="NULLABLE"),
    ]
    # Shared JQL for all modes
    jql_query = (
        '('
        'project = "GS&O Data Analytics" OR '
        'project = "GS&O Tool Automation" OR '
        'project = "GS&O Knowledge Consolidation" OR '
        'project = "Google Contact Center AI Solution" OR '
        'project = TAC OR '
        'project = CCAS OR '
        'project = VOICECE OR '
        'project = IOTCE OR '
        'project = TXCE OR '
        'project = SMSCE OR '
        'project = MSS OR '
        'project = "Console Application Support" OR '
        'project = "Console Connect Provisioning" OR '
        'project = "Global Service Delivery Team" OR '
        'project = "Transmission TX-CE" OR '
        'project = "Mobility SMS - CE" OR '
        'project = "Managed Security Services"'
        ') AND updated >= -3h'
    )
    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
        logging.error("Setup failed: Could not create temp table.")
        return
    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error("Setup failed: Temp table not available.")
        return
    rows_to_insert = []
    total_issues = float('inf')
    start_at = 0
    max_results = 100
    search_url = f"{jira_base_url}/rest/api/2/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)
    def fetch_comments_for_issue(issue_key):
        all_comments = []
        start_at_c = 0
        while True:
            url = f"{jira_base_url}/rest/api/2/issue/{issue_key}/comment"
            params = {"startAt": start_at_c, "maxResults": 75}
            try:
                resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, params=params, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                comments = data.get('comments', [])
                all_comments.extend(comments)
                total_comments = data.get('total', 0)
                if start_at_c + len(comments) >= total_comments:
                    break
                start_at_c += len(comments)
            except Exception as e:
                logging.warning(f"Error fetching comments for {issue_key}: {e}")
                return None
        return all_comments
    while start_at < total_issues:
        payload = json.dumps({
            "jql": jql_query,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["key"]
        })
        try:
            response = requests.post(search_url, headers=headers, auth=auth, data=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            issues = data.get('issues', [])
            total_issues = data.get('total', 0)
            issue_keys = [issue.get('key') for issue in issues if issue.get('key')]
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_key = {executor.submit(fetch_comments_for_issue, key): key for key in issue_keys}
                for future in as_completed(future_to_key):
                    comments = future.result()
                    if comments is None:
                        continue
                    for comment in comments:
                        row = {
                            "Issue_Key": comment.get('self', '').split('/')[-3],
                            "Comment_ID": comment.get('id'),
                            "Author_Account_ID": comment.get('author', {}).get('accountId'),
                            "Author_Display_Name": comment.get('author', {}).get('displayName'),
                            "Created": convert_timestamp(comment.get('created')),
                            "Updated": convert_timestamp(comment.get('updated')),
                            "Body": comment.get('body'),
                            "Visibility_Type": comment.get('visibility', {}).get('type'),
                            "Visibility_Value": comment.get('visibility', {}).get('value'),
                            "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                            "InsertedAt": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                        }
                        rows_to_insert.append(row)
            start_at += len(issues)
            logging.info(f"Fetched and processed {len(issues)} issues (startAt: {start_at}) out of total {total_issues}")
            if not issues:
                break
        except Exception as e:
            logging.error(f"Error fetching issues or comments from Jira: {e}")
            break
    if rows_to_insert:
        if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, bq_schema, retries=5, delay=5):
            logging.error("Failed to insert rows into temp table after retries.")
            delete_temp_table(client, dataset_id, temp_table_id)
            return
    merge_fields = [
        "Issue_Key", "Comment_ID", "Author_Account_ID", "Author_Display_Name", "Created", "Updated", "Body", "Visibility_Type", "Visibility_Value", "SyncTime", "InsertedAt"
    ]
    try:
        merge_query = f'''
            MERGE `{dataset_id}.{table_id}` T
            USING `{dataset_id}.{temp_table_id}` S
            ON T.Comment_ID = S.Comment_ID AND T.Updated = S.Updated
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
    delete_temp_table(client, dataset_id, temp_table_id)

# --- Changelog Sync Logic ---
def sync_changelog(config, client, dataset_id, run_id):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jira_base_url = 'https://consoleconnect.atlassian.net'
    username = 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')
    table_id = 'JiraChangelog'
    temp_table_id = 'JiraChangelog_temp'
    pipeline_name = "jira_changelog"
    bq_schema = [
        bigquery.SchemaField("Issue_Key", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("History_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transition_Timestamp", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_From", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_To", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Account_ID", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Transitioned_By_Display_Name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
    ]
    # Shared JQL for all modes
    jql_query = (
        '('
        'project = "GS&O Data Analytics" OR '
        'project = "GS&O Tool Automation" OR '
        'project = "GS&O Knowledge Consolidation" OR '
        'project = "Google Contact Center AI Solution" OR '
        'project = TAC OR '
        'project = CCAS OR '
        'project = VOICECE OR '
        'project = IOTCE OR '
        'project = TXCE OR '
        'project = SMSCE OR '
        'project = MSS OR '
        'project = "Console Application Support" OR '
        'project = "Console Connect Provisioning" OR '
        'project = "Global Service Delivery Team" OR '
        'project = "Transmission TX-CE" OR '
        'project = "Mobility SMS - CE" OR '
        'project = "Managed Security Services"'
        ') AND updated >= -3h'
    )
    if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
        logging.error("Setup failed: Could not create temp table.")
        return
    if not wait_for_table(client, dataset_id, temp_table_id):
        logging.error("Setup failed: Temp table not available.")
        return
    rows_to_insert = []
    total_issues = float('inf')
    start_at = 0
    max_results = 100
    search_url = f"{jira_base_url}/rest/api/2/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)
    def fetch_changelog_for_issue(issue_key):
        url = f"{jira_base_url}/rest/api/2/issue/{issue_key}?expand=changelog"
        try:
            resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            changelog = data.get('changelog', {})
            histories = changelog.get('histories', [])
            rows = []
            for h in histories:
                for item in h.get('items', []):
                    if item.get('field') == 'status':
                        rows.append({
                            "Issue_Key": issue_key,
                            "History_ID": h.get('id'),
                            "Transition_Timestamp": convert_timestamp(h.get('created')),
                            "Transitioned_From": item.get('fromString'),
                            "Transitioned_To": item.get('toString'),
                            "Transitioned_By_Account_ID": h.get('author', {}).get('accountId'),
                            "Transitioned_By_Display_Name": h.get('author', {}).get('displayName'),
                            "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                        })
            return rows
        except Exception as e:
            logging.warning(f"Error fetching changelog for {issue_key}: {e}")
            return []
    while start_at < total_issues:
        payload = json.dumps({
            "jql": jql_query,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["key"]
        })
        try:
            response = requests.post(search_url, headers=headers, auth=auth, data=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            issues = data.get('issues', [])
            total_issues = data.get('total', 0)
            issue_keys = [issue.get('key') for issue in issues if issue.get('key')]
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_key = {executor.submit(fetch_changelog_for_issue, key): key for key in issue_keys}
                for future in as_completed(future_to_key):
                    rows = future.result()
                    if rows:
                        rows_to_insert.extend(rows)
            start_at += len(issues)
            logging.info(f"Fetched and processed {len(issues)} issues (startAt: {start_at}) out of total {total_issues}")
            if not issues:
                break
        except Exception as e:
            logging.error(f"Error fetching issues or changelog from Jira: {e}")
            break
    if rows_to_insert:
        if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, bq_schema, retries=5, delay=5):
            logging.error("Failed to insert rows into temp table after retries.")
            delete_temp_table(client, dataset_id, temp_table_id)
            return
    merge_fields = [
        "Issue_Key", "History_ID", "Transition_Timestamp", "Transitioned_From", "Transitioned_To", "Transitioned_By_Account_ID", "Transitioned_By_Display_Name", "SyncTime"
    ]
    try:
        merge_query = f'''
            MERGE `{dataset_id}.{table_id}` T
            USING `{dataset_id}.{temp_table_id}` S
            ON T.History_ID = S.History_ID AND T.Transition_Timestamp = S.Transition_Timestamp
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
    delete_temp_table(client, dataset_id, temp_table_id)

def main():
    parser = argparse.ArgumentParser(description="Jira to BigQuery Sync Pipeline")
    parser.add_argument('--mode', choices=['tickets', 'comments', 'changelog', 'all'], required=True, help='Which Jira data to sync')
    args = parser.parse_args()

    config = load_config()
    if config is None:
        return

    client = bigquery.Client()
    dataset_id = 'GSO'
    run_id = str(uuid.uuid4())

    # Log pipeline start
    log_to_bigquery(client, dataset_id, "PipelineLogs", args.mode, run_id, "INFO", "Pipeline started", function_name="main")

    try:
        if args.mode == 'tickets':
            sync_tickets(config, client, dataset_id, run_id)
        elif args.mode == 'comments':
            sync_comments(config, client, dataset_id, run_id)
        elif args.mode == 'changelog':
            sync_changelog(config, client, dataset_id, run_id)
        elif args.mode == 'all':
            sync_tickets(config, client, dataset_id, run_id)
            sync_comments(config, client, dataset_id, run_id)
            sync_changelog(config, client, dataset_id, run_id)
    except Exception as e:
        logging.exception(f"Pipeline failed: {e}")
        log_to_bigquery(client, dataset_id, "PipelineLogs", args.mode, run_id, "ERROR", f"Exception: {e}", function_name="main", details=str(e))
    finally:
        log_to_bigquery(client, dataset_id, "PipelineLogs", args.mode, run_id, "INFO", "Pipeline finished", function_name="main")
        # Optionally flush logs if you buffer them

if __name__ == '__main__':
    main()