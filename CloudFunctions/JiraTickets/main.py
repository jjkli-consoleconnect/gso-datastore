"""
Cloud Function: Jira Tickets Sync
Syncs Jira ticket data from consoleconnect.atlassian.net to BigQuery.
Routes through VPC to access Jira behind VPN.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import logging
import re
import uuid
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, secretmanager
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError
import functions_framework

# Import shared helper functions from local copy
from jira_helpers import (
    load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table, 
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

# Setup logging
setup_root_logging()

# Jitter used when sleeping after 429s
JITTER_MAX_SECONDS = 0.3

# Rate limiting settings (Jira Cloud: ~180 req/min = ~3 req/sec)
JIRA_RATE_LIMIT_PAUSE_SEC = 0.4  # Pause between paginated searches


def handle_429_backoff(response, attempt=1, max_attempts=3):
    """Handle 429 rate limit with exponential backoff."""
    if response.status_code != 429 or attempt >= max_attempts:
        return False
    retry_after = int(response.headers.get('Retry-After', 30) or 30)
    backoff_time = min(retry_after * (2 ** (attempt - 1)), 120)  # Cap at 2 minutes
    wait_time = backoff_time + random.uniform(0, JITTER_MAX_SECONDS)
    logging.warning(f"429 Rate limit (attempt {attempt}/{max_attempts}). Waiting {wait_time:.1f}s")
    time.sleep(wait_time)
    return True


def create_session_with_retries():
    """Create a requests Session with connection pooling and retry strategy."""
    session = requests.Session()
    
    # Configure retry strategy for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # exponential backoff: 1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    # Apply to both http and https - increased pool to match concurrency (20 parallel workers)
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=30, pool_maxsize=30)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session


def send_error_email(error_message, project_id="pccw-internal-virtual-agent"):
    """Send error notification. Try SendGrid (if configured), fall back to SMTP."""
    try:
        recipient = get_secret("jira-sync-alert-recipient", project_id)

        # Try SendGrid first (recommended when Gmail app passwords are blocked)
        try:
            sendgrid_api_key = get_secret("jira-sync-sendgrid-api-key", project_id)
        except Exception:
            sendgrid_api_key = None

        if sendgrid_api_key:
            try:
                from_email = get_secret("jira-sync-alert-email", project_id)
            except Exception:
                from_email = f"no-reply@{project_id}.iam.gserviceaccount.com"

            payload = {
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": {"email": from_email},
                "subject": "⚠️ Jira Tickets Sync FAILED",
                "content": [{"type": "text/plain", "value": (
                    f"Jira Tickets Sync has FAILED.\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\nFunction: jira-tickets-sync\n\nError Details:\n{error_message}\n\nCheck Cloud Function logs: https://console.cloud.google.com/functions/details/europe-west2/jira-tickets-sync?project={project_id}"
                )}]
            }
            headers = {"Authorization": f"Bearer {sendgrid_api_key}", "Content-Type": "application/json"}
            try:
                r = requests.post("https://api.sendgrid.com/v3/mail/send", headers=headers, json=payload, timeout=10)
                if r.status_code >= 300:
                    logging.error(f"SendGrid send failed ({r.status_code}): {r.text}")
                else:
                    logging.info("Error notification sent via SendGrid")
                    return
            except Exception as ex:
                logging.error(f"SendGrid send exception: {ex}")

        # Fallback to SMTP (Gmail) if SendGrid not configured or failed
        try:
            smtp_user = get_secret("jira-sync-alert-email", project_id)
            smtp_password = get_secret("jira-sync-alert-password", project_id)
        except Exception:
            smtp_user = None
            smtp_password = None

        if smtp_user and smtp_password:
            try:
                msg = MIMEMultipart()
                msg['From'] = smtp_user
                msg['To'] = recipient
                msg['Subject'] = "⚠️ Jira Tickets Sync FAILED"
                body = (
                    f"Jira Tickets Sync has FAILED.\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\nFunction: jira-tickets-sync\n\nError Details:\n{error_message}\n\nCheck Cloud Function logs: https://console.cloud.google.com/functions/details/europe-west2/jira-tickets-sync?project={project_id}"
                )
                msg.attach(MIMEText(body, 'plain'))
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                logging.info("Error notification email sent via SMTP")
                return
            except Exception as ex:
                logging.error(f"SMTP send failed: {ex}")

        logging.error("No email provider configured or all providers failed to send the error notification")
    except Exception as e:
        logging.error(f"Failed to send error notification: {e}")


def get_secret(secret_id, project_id="pccw-internal-virtual-agent"):
    """Retrieve secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')


def ensure_ticket_columns(client, dataset_id, table_id):
    """Ensure newly tracked ticket custom-field columns exist on the target table."""
    table_ref = f"{client.project}.{dataset_id}.{table_id}"
    try:
        existing_columns = {field.name for field in client.get_table(table_ref).schema}
    except Exception:
        existing_columns = set()

    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS AssociatedTeam STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS TransactionStatus STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Service STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Origin STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS RootCause STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS ResolutionSecurity STRING"
    ).result()
    client.query(
        f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Symptoms STRING"
    ).result()

    if 'TranscationStatus' in existing_columns:
        client.query(
            f"""
            UPDATE `{dataset_id}.{table_id}`
            SET TransactionStatus = COALESCE(TransactionStatus, TranscationStatus)
            WHERE TranscationStatus IS NOT NULL
            """
        ).result()


def load_config():
    """Load Jira config from Secret Manager instead of config.json."""
    try:
        api_token = get_secret("jira-api-token")
        user_email = get_secret("jira-user-email")
        return {
            'jira_api_token': api_token,
            'jira_user': user_email
        }
    except Exception as e:
        logging.error(f"Failed to load config from Secret Manager: {e}")
        return None


def get_field_value(field):
    """Handles various field types, returns a string representation."""
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
    """
    Extracts a readable summary of issue links from the Jira 'issuelinks' field.
    """
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
                    links.append(f"{link.get('type', {}).get('outward', 'links to')}: {key} [{status}]")
                else:
                    links.append(f"{link.get('type', {}).get('outward', 'links to')}: {key}")
        if inward:
            key = inward.get('key')
            status = get_status(inward)
            if key:
                if status:
                    links.append(f"{link.get('type', {}).get('inward', 'links to')}: {key} [{status}]")
                else:
                    links.append(f"{link.get('type', {}).get('inward', 'links to')}: {key}")
    return ', '.join(links) if links else None


def extract_incident_numbers(remedy_ticket_number):
    """Extracts all incident numbers matching INC followed by 9+ digits."""
    if not remedy_ticket_number:
        return []
    return re.findall(r'INC\d{9,}', str(remedy_ticket_number))


def transform_sr_ref(value):
    """Remove leading/trailing spaces and all 'SR' (case-insensitive) from the value."""
    if value is None:
        return None
    value = str(value).strip()
    value = value.replace('SR', '').replace('sr', '').replace('Sr', '').replace('sR', '')
    return value


def fetch_and_sync_jira_data():
    """Main sync function - same logic as local script."""
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    username = config.get('jira_user', 'jjkli@consoleconnect.com')
    api_token = config.get('jira_api_token')
    
    CHUNK_SIZE = 1000
    RETRY_COUNT = 5
    RETRY_DELAY = 5

    # Custom field configuration
    SR_REF_JIRA_ID = 'customfield_10382'
    SR_REF_BQ_NAME = 'SR_Ref'
    ASSOCIATED_TEAM_JIRA_ID = 'customfield_11134'
    ASSOCIATED_TEAM_BQ_NAME = 'AssociatedTeam'
    TRANSACTION_STATUS_JIRA_ID = 'customfield_11170'
    TRANSACTION_STATUS_BQ_NAME = 'TransactionStatus'
    SERVICE_JIRA_ID = 'customfield_11350'
    SERVICE_BQ_NAME = 'Service'
    ORIGIN_JIRA_ID = 'customfield_11351'
    ORIGIN_BQ_NAME = 'Origin'
    ROOT_CAUSE_JIRA_ID = 'customfield_10775'
    ROOT_CAUSE_BQ_NAME = 'RootCause'
    RESOLUTION_SECURITY_JIRA_ID = 'customfield_11349'
    RESOLUTION_SECURITY_BQ_NAME = 'ResolutionSecurity'
    SYMPTOMS_JIRA_ID = 'customfield_11365'
    SYMPTOMS_BQ_NAME = 'Symptoms'

    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    pipeline_name = "GCP - JiraTickets"
    
    run_id = str(uuid.uuid4())
    client = None
    
    try:
        run_started = datetime.now(timezone.utc)
        
        # Use UAT project for BigQuery where GSO dataset exists
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        project_id = client.project
        dataset_id = 'GSO'

        ensure_ticket_columns(client, dataset_id, table_id)
        
        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

        # Load base JQL
        base_default = (
            '('\
            'project = "GS&O Data Analytics" OR '\
            'project = "Customer Success Management" OR '\
            'project = "GS&O Tool Automation" OR '\
            'project = "GS&O Knowledge Consolidation" OR '\
            'project = TAC OR '\
            'project = "VOICE - CE" OR '\
            'project = "IOT CE" OR '\
            'project = "Console Application Support" OR '\
            'project = "Console Connect Provisioning" OR '\
            'project = "Global Service Delivery Team" OR '\
            'project = "Transmission TX-CE" OR '\
            'project = "Mobility SMS - CE" OR '\
            'project = "Managed Security Services" OR '\
            'project = Sherbet OR '\
            'project = "Google Contact Center AI Solution" OR '\
            'project = "QMS Documentation" OR '\
            'project = "Operational Case Reviews" OR '\
            'project = "IT Helpdesk" OR '\
            'project = "Vendor Verification Team" OR '\
            'project = "GS&O Strategic Initiatives" '
            ')'
        )
        base_jql = load_base_jql(default_text=base_default)
        logging.info(f"Resolved base_jql: {base_jql}")
        
        if not base_jql:
            # Log and mark pipeline as ERROR before exiting
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="No base JQL resolved",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return

        # Optimized single-pass approach: capture ANY activity in last 1 hour
        # Includes: field updates, resolutions, and new comments
        jql_any_activity = build_jql(base_jql, "(updated >= -1h OR resolutiondate >= -1h OR comment.updated >= -1h)", joiner='AND')
        logging.info(f"JQL (any activity in last 1h): {jql_any_activity}")

        jql_window_start = run_started - timedelta(hours=1)
        jql_window_end = run_started

        # BigQuery schema (all fields exactly as in original)
        bq_schema = [
            bigquery.SchemaField("T", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Project", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Priority", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Resolution", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Component", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SR_REF_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToFirstResponse_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolve_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToApproveNormalChange_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ProlongCase_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("TimeToCloseAfterResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("AppSupEscalation", "STRING", mode="NULLABLE"),
            bigquery.SchemaField(ASSOCIATED_TEAM_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(TRANSACTION_STATUS_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SERVICE_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(ORIGIN_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(ROOT_CAUSE_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(RESOLUTION_SECURITY_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField(SYMPTOMS_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField("StoryPoints", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToFirstResponse_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToFirstResponse_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToFirstResponse_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToFirstResponse_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToResolution_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToResolution_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_TimeToResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResponse_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResponse_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResponse_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResponse_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResolution_Elapsed_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResolution_Goal_hrs", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResolution_Breached", "BOOL", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_ISMSIncidentResolution_Cycles", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("ITHD_Resolution", "STRING", mode="NULLABLE"),
        ]
        
        if not create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
            logging.error("Setup failed: Could not create temp table.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Could not create temp table",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error("Setup failed: Temp table not available.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Temp table not available",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return

        rows_to_insert = []
        issue_keys_total = set()
        BULK_FETCH_SIZE = 50

        def extract_sla_metrics(sla_field):
            if not isinstance(sla_field, dict):
                return None, None, None, None
            
            ongoing = sla_field.get('ongoingCycle')
            completed_cycles = sla_field.get('completedCycles', [])
            
            if ongoing:
                cycle = ongoing
                num_cycles = len(completed_cycles)
            elif completed_cycles:
                cycle = completed_cycles[-1]
                num_cycles = len(completed_cycles)
            else:
                return None, None, None, 0
            
            elapsed_millis = cycle.get('elapsedTime', {}).get('millis') if isinstance(cycle.get('elapsedTime'), dict) else None
            goal_millis = cycle.get('goalDuration', {}).get('millis')
            breached = cycle.get('breached', False)
            
            elapsed = elapsed_millis / 3600000.0 if elapsed_millis is not None else None
            goal = goal_millis / 3600000.0 if goal_millis else None
            
            return elapsed, goal, breached, num_cycles

        def fetch_issue_detail(issue_key, session):
            issue_url = f"https://consoleconnect.atlassian.net/rest/api/3/issue/{issue_key}"
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            auth = (username, api_token)
            try:
                issue_resp = session.get(issue_url, headers=headers, auth=auth, timeout=30)
                issue_resp.raise_for_status()
                full_issue = issue_resp.json()
                fields = full_issue.get('fields', {})
                
                # Extract SLA metrics
                sla_fields = {
                    'TimeToFirstResponse': fields.get('customfield_10627'),
                    'TimeToResolve': fields.get('customfield_10686'),
                    'TimeToResolution': fields.get('customfield_10668'),
                    'TimeToApproveNormalChange': fields.get('customfield_10640'),
                    'ProlongCase': fields.get('customfield_10560'),
                    'TimeToCloseAfterResolution': fields.get('customfield_10552'),
                    'ITHD_TimeToFirstResponse': fields.get('customfield_10627'),
                    'ITHD_TimeToResolution': fields.get('customfield_10668'),
                    'ITHD_ISMSIncidentResponse': fields.get('customfield_13449'),
                    'ITHD_ISMSIncidentResolution': fields.get('customfield_13450'),
                }
                
                sla_metrics = {}
                for k, v in sla_fields.items():
                    elapsed, goal, breached, cycles = extract_sla_metrics(v)
                    sla_metrics[f'{k}_Elapsed'] = elapsed
                    sla_metrics[f'{k}_Goal'] = goal
                    sla_metrics[f'{k}_Breached'] = breached
                    sla_metrics[f'{k}_Cycles'] = cycles

                issue_type = fields.get('issuetype', {}).get('name')
                cf_val = fields.get('customfield_10088')  # Remedy ticket field
                remedy_source = ' | '.join([
                    str(cf_val) if cf_val else '',
                    str(fields.get('summary') or ''),
                    str(fields.get('description') or ''),
                ]).strip(' |')
                remedy_numbers = extract_incident_numbers(remedy_source)

                row = {
                    "T": issue_type,
                    "Project": fields.get('project', {}).get('name'),
                    "Key": issue_key,
                    "Summary": fields.get('summary'),
                    "Status": fields.get('status', {}).get('name'),
                    "Created": convert_timestamp(fields.get('created')),
                    "Updated": convert_timestamp(fields.get('updated')),
                    "Resolved": convert_timestamp(fields.get('resolutiondate')),
                    "Reporter": get_field_value(fields.get('reporter')),
                    "Assignee": get_field_value(fields.get('assignee')),
                    "Component": ', '.join([get_field_value(c) for c in fields.get('components', [])]) if fields.get('components') else None,
                    "RemedyTicketNumber": ', '.join(remedy_numbers) if remedy_numbers else None,
                    "Links": extract_issue_links(fields.get('issuelinks')),
                    SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
                    "Priority": get_field_value(fields.get('priority')),
                    "Resolution": get_field_value(fields.get('resolution')),
                    "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    "TimeToFirstResponse_Elapsed_hrs": sla_metrics['TimeToFirstResponse_Elapsed'],
                    "TimeToFirstResponse_Goal_hrs": sla_metrics['TimeToFirstResponse_Goal'],
                    "TimeToFirstResponse_Breached": sla_metrics['TimeToFirstResponse_Breached'],
                    "TimeToFirstResponse_Cycles": sla_metrics['TimeToFirstResponse_Cycles'],
                    "TimeToResolve_Elapsed_hrs": sla_metrics['TimeToResolve_Elapsed'],
                    "TimeToResolve_Goal_hrs": sla_metrics['TimeToResolve_Goal'],
                    "TimeToResolve_Breached": sla_metrics['TimeToResolve_Breached'],
                    "TimeToResolve_Cycles": sla_metrics['TimeToResolve_Cycles'],
                    "TimeToResolution_Elapsed_hrs": sla_metrics['TimeToResolution_Elapsed'],
                    "TimeToResolution_Goal_hrs": sla_metrics['TimeToResolution_Goal'],
                    "TimeToResolution_Breached": sla_metrics['TimeToResolution_Breached'],
                    "TimeToResolution_Cycles": sla_metrics['TimeToResolution_Cycles'],
                    "TimeToApproveNormalChange_Elapsed_hrs": sla_metrics['TimeToApproveNormalChange_Elapsed'],
                    "TimeToApproveNormalChange_Goal_hrs": sla_metrics['TimeToApproveNormalChange_Goal'],
                    "TimeToApproveNormalChange_Breached": sla_metrics['TimeToApproveNormalChange_Breached'],
                    "TimeToApproveNormalChange_Cycles": sla_metrics['TimeToApproveNormalChange_Cycles'],
                    "ProlongCase_Elapsed_hrs": sla_metrics['ProlongCase_Elapsed'],
                    "ProlongCase_Goal_hrs": sla_metrics['ProlongCase_Goal'],
                    "ProlongCase_Breached": sla_metrics['ProlongCase_Breached'],
                    "ProlongCase_Cycles": sla_metrics['ProlongCase_Cycles'],
                    "TimeToCloseAfterResolution_Elapsed_hrs": sla_metrics['TimeToCloseAfterResolution_Elapsed'],
                    "TimeToCloseAfterResolution_Goal_hrs": sla_metrics['TimeToCloseAfterResolution_Goal'],
                    "TimeToCloseAfterResolution_Breached": sla_metrics['TimeToCloseAfterResolution_Breached'],
                    "TimeToCloseAfterResolution_Cycles": sla_metrics['TimeToCloseAfterResolution_Cycles'],
                    "AppSupEscalation": get_field_value(fields.get('customfield_11171')),
                    ASSOCIATED_TEAM_BQ_NAME: get_field_value(fields.get(ASSOCIATED_TEAM_JIRA_ID)),
                    TRANSACTION_STATUS_BQ_NAME: get_field_value(fields.get(TRANSACTION_STATUS_JIRA_ID)),
                    SERVICE_BQ_NAME: get_field_value(fields.get(SERVICE_JIRA_ID)),
                    ORIGIN_BQ_NAME: get_field_value(fields.get(ORIGIN_JIRA_ID)),
                    ROOT_CAUSE_BQ_NAME: get_field_value(fields.get(ROOT_CAUSE_JIRA_ID)),
                    RESOLUTION_SECURITY_BQ_NAME: get_field_value(fields.get(RESOLUTION_SECURITY_JIRA_ID)),
                    SYMPTOMS_BQ_NAME: get_field_value(fields.get(SYMPTOMS_JIRA_ID)),
                    "StoryPoints": (None if fields.get('customfield_10347') is None else (
                        (lambda v: (int(float(v)) if v is not None else None))(get_field_value(fields.get('customfield_10347')))
                    )),
                    "ITHD_TimeToFirstResponse_Elapsed_hrs": sla_metrics['ITHD_TimeToFirstResponse_Elapsed'],
                    "ITHD_TimeToFirstResponse_Goal_hrs": sla_metrics['ITHD_TimeToFirstResponse_Goal'],
                    "ITHD_TimeToFirstResponse_Breached": sla_metrics['ITHD_TimeToFirstResponse_Breached'],
                    "ITHD_TimeToFirstResponse_Cycles": sla_metrics['ITHD_TimeToFirstResponse_Cycles'],
                    "ITHD_TimeToResolution_Elapsed_hrs": sla_metrics['ITHD_TimeToResolution_Elapsed'],
                    "ITHD_TimeToResolution_Goal_hrs": sla_metrics['ITHD_TimeToResolution_Goal'],
                    "ITHD_TimeToResolution_Breached": sla_metrics['ITHD_TimeToResolution_Breached'],
                    "ITHD_TimeToResolution_Cycles": sla_metrics['ITHD_TimeToResolution_Cycles'],
                    "ITHD_ISMSIncidentResponse_Elapsed_hrs": sla_metrics['ITHD_ISMSIncidentResponse_Elapsed'],
                    "ITHD_ISMSIncidentResponse_Goal_hrs": sla_metrics['ITHD_ISMSIncidentResponse_Goal'],
                    "ITHD_ISMSIncidentResponse_Breached": sla_metrics['ITHD_ISMSIncidentResponse_Breached'],
                    "ITHD_ISMSIncidentResponse_Cycles": sla_metrics['ITHD_ISMSIncidentResponse_Cycles'],
                    "ITHD_ISMSIncidentResolution_Elapsed_hrs": sla_metrics['ITHD_ISMSIncidentResolution_Elapsed'],
                    "ITHD_ISMSIncidentResolution_Goal_hrs": sla_metrics['ITHD_ISMSIncidentResolution_Goal'],
                    "ITHD_ISMSIncidentResolution_Breached": sla_metrics['ITHD_ISMSIncidentResolution_Breached'],
                    "ITHD_ISMSIncidentResolution_Cycles": sla_metrics['ITHD_ISMSIncidentResolution_Cycles'],
                    "ITHD_Resolution": get_field_value(fields.get('customfield_13448')),
                }
                return row
            except Exception as e:
                logging.warning(f"Could not fetch full details for issue {issue_key}: {e}")
                return None

        observed_min_updated = None
        observed_max_updated = None

        # Create persistent session with connection pooling and retry logic
        session = create_session_with_retries()
        
        def search_issue_keys_paginated(jql: str, label: str):
            """Fetch ALL matching issue keys with pagination. CRITICAL: Prevents data loss!"""
            all_keys = []
            start_at = 0
            max_results = 100
            headers_local = {'Accept': 'application/json'}
            auth_local = (username, api_token)
            attempt = 0
            max_attempts = 3
            
            while True:
                params_local = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': 'key'}
                try:
                    resp = session.get(jira_url, headers=headers_local, auth=auth_local, params=params_local, timeout=60)
                    
                    if resp.status_code == 429:
                        if handle_429_backoff(resp, attempt + 1, max_attempts):
                            attempt += 1
                            continue
                        else:
                            logging.error(f"Failed after {max_attempts} 429 attempts on {label}")
                            break
                    
                    resp.raise_for_status()
                    attempt = 0  # Reset on success
                    
                    data_local = resp.json()
                    issues_local = data_local.get('issues', [])
                    if not issues_local:
                        break
                    
                    all_keys.extend([i.get('key') for i in issues_local if i.get('key')])
                    total = data_local.get('total', 0)
                    
                    if start_at + max_results >= total:
                        break
                    
                    start_at += max_results
                    time.sleep(JIRA_RATE_LIMIT_PAUSE_SEC)  # Respect rate limits
                    
                except requests.exceptions.Timeout:
                    logging.warning(f"Timeout fetching keys for {label} at startAt={start_at}")
                    break
                except Exception as e:
                    logging.error(f"Error fetching keys for {label}: {e}")
                    break
            
            logging.info(f"{label}: Fetched {len(all_keys)} total issue keys (paginated)")
            return all_keys

        # Single-pass optimized approach: captures any activity (updates, resolutions, comments)
        # CRITICAL: Using pagination to get ALL matching issues, not just first 100!
        activity_keys = search_issue_keys_paginated(jql_any_activity, 'any_activity')
        for k in activity_keys: issue_keys_total.add(k)
        logging.info(f"Distinct issue keys to detail fetch (union): {len(issue_keys_total)}")

        # Detail fetch in parallel with increased workers to match connection pool (30)
        issue_key_list = list(issue_keys_total)
        issues_processed = 0
        MAX_WORKERS = 20  # Increased from 10 to match pool_connections=30
        for i in range(0, len(issue_key_list), BULK_FETCH_SIZE):
            batch_keys = issue_key_list[i:i+BULK_FETCH_SIZE]
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batch_keys))) as executor:
                fut_map = {executor.submit(fetch_issue_detail, key, session): key for key in batch_keys}
                for fut in as_completed(fut_map):
                    row = fut.result()
                    if row:
                        rows_to_insert.append(row)
                        issues_processed += 1
                        try:
                            upd_str = row.get("Updated")
                            if upd_str:
                                dt = datetime.strptime(upd_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                                if observed_min_updated is None or dt < observed_min_updated:
                                    observed_min_updated = dt
                                if observed_max_updated is None or dt > observed_max_updated:
                                    observed_max_updated = dt
                        except Exception:
                            pass
            logging.info(f"Detail fetched batch {i//BULK_FETCH_SIZE + 1}; cumulative rows={issues_processed}")

        # Close session to release connections
        session.close()

        if rows_to_insert:
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows_to_insert, bq_schema, retries=5, delay=5):
                logging.error("Failed to insert rows into temp table after retries.")
                delete_temp_table(client, dataset_id, temp_table_id)
                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="ERROR",
                    message="Failed to insert rows into temp table",
                    status="ERROR",
                    duration_seconds=duration_seconds,
                )
                return

        # Merge temp table into final table (exact same query as original)
        try:
            merge_query = f'''
                MERGE `{dataset_id}.{table_id}` T
                USING (
                    SELECT * EXCEPT(rownum) FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum FROM `{dataset_id}.{temp_table_id}`
                    ) WHERE rownum = 1
                ) S
                ON T.Key = S.Key
                WHEN MATCHED THEN UPDATE SET
                    T.T = S.T,
                    T.Project = S.Project,
                    T.Summary = S.Summary,
                    T.Status = S.Status,
                    T.Priority = S.Priority,
                    T.Resolution = S.Resolution,
                    T.Created = S.Created,
                    T.Updated = S.Updated,
                    T.Resolved = S.Resolved,
                    T.Reporter = S.Reporter,
                    T.Assignee = S.Assignee,
                    T.Component = IF(S.Component IS NULL, NULL, [S.Component]),
                    T.RemedyTicketNumber = IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]),
                    T.Links = S.Links,
                    T.{SR_REF_BQ_NAME} = S.{SR_REF_BQ_NAME},
                    T.SyncTime = S.SyncTime,
                    T.TimeToFirstResponse_Elapsed_hrs = S.TimeToFirstResponse_Elapsed_hrs,
                    T.TimeToFirstResponse_Goal_hrs = S.TimeToFirstResponse_Goal_hrs,
                    T.TimeToFirstResponse_Breached = S.TimeToFirstResponse_Breached,
                    T.TimeToFirstResponse_Cycles = S.TimeToFirstResponse_Cycles,
                    T.TimeToResolve_Elapsed_hrs = S.TimeToResolve_Elapsed_hrs,
                    T.TimeToResolve_Goal_hrs = S.TimeToResolve_Goal_hrs,
                    T.TimeToResolve_Breached = S.TimeToResolve_Breached,
                    T.TimeToResolve_Cycles = S.TimeToResolve_Cycles,
                    T.TimeToResolution_Elapsed_hrs = S.TimeToResolution_Elapsed_hrs,
                    T.TimeToResolution_Goal_hrs = S.TimeToResolution_Goal_hrs,
                    T.TimeToResolution_Breached = S.TimeToResolution_Breached,
                    T.TimeToResolution_Cycles = S.TimeToResolution_Cycles,
                    T.TimeToApproveNormalChange_Elapsed_hrs = S.TimeToApproveNormalChange_Elapsed_hrs,
                    T.TimeToApproveNormalChange_Goal_hrs = S.TimeToApproveNormalChange_Goal_hrs,
                    T.TimeToApproveNormalChange_Breached = S.TimeToApproveNormalChange_Breached,
                    T.TimeToApproveNormalChange_Cycles = S.TimeToApproveNormalChange_Cycles,
                    T.ProlongCase_Elapsed_hrs = S.ProlongCase_Elapsed_hrs,
                    T.ProlongCase_Goal_hrs = S.ProlongCase_Goal_hrs,
                    T.ProlongCase_Breached = S.ProlongCase_Breached,
                    T.ProlongCase_Cycles = S.ProlongCase_Cycles,
                    T.TimeToCloseAfterResolution_Elapsed_hrs = S.TimeToCloseAfterResolution_Elapsed_hrs,
                    T.TimeToCloseAfterResolution_Goal_hrs = S.TimeToCloseAfterResolution_Goal_hrs,
                    T.TimeToCloseAfterResolution_Breached = S.TimeToCloseAfterResolution_Breached,
                    T.TimeToCloseAfterResolution_Cycles = S.TimeToCloseAfterResolution_Cycles,
                    T.AppSupEscalation = S.AppSupEscalation,
                    T.AssociatedTeam = S.AssociatedTeam,
                    T.TransactionStatus = S.TransactionStatus,
                    T.Service = S.Service,
                    T.Origin = S.Origin,
                    T.RootCause = S.RootCause,
                    T.ResolutionSecurity = S.ResolutionSecurity,
                    T.Symptoms = S.Symptoms,
                    T.StoryPoints = S.StoryPoints,
                    T.ITHD_TimeToFirstResponse_Elapsed_hrs = S.ITHD_TimeToFirstResponse_Elapsed_hrs,
                    T.ITHD_TimeToFirstResponse_Goal_hrs = S.ITHD_TimeToFirstResponse_Goal_hrs,
                    T.ITHD_TimeToFirstResponse_Breached = S.ITHD_TimeToFirstResponse_Breached,
                    T.ITHD_TimeToFirstResponse_Cycles = S.ITHD_TimeToFirstResponse_Cycles,
                    T.ITHD_TimeToResolution_Elapsed_hrs = S.ITHD_TimeToResolution_Elapsed_hrs,
                    T.ITHD_TimeToResolution_Goal_hrs = S.ITHD_TimeToResolution_Goal_hrs,
                    T.ITHD_TimeToResolution_Breached = S.ITHD_TimeToResolution_Breached,
                    T.ITHD_TimeToResolution_Cycles = S.ITHD_TimeToResolution_Cycles,
                    T.ITHD_ISMSIncidentResponse_Elapsed_hrs = S.ITHD_ISMSIncidentResponse_Elapsed_hrs,
                    T.ITHD_ISMSIncidentResponse_Goal_hrs = S.ITHD_ISMSIncidentResponse_Goal_hrs,
                    T.ITHD_ISMSIncidentResponse_Breached = S.ITHD_ISMSIncidentResponse_Breached,
                    T.ITHD_ISMSIncidentResponse_Cycles = S.ITHD_ISMSIncidentResponse_Cycles,
                    T.ITHD_ISMSIncidentResolution_Elapsed_hrs = S.ITHD_ISMSIncidentResolution_Elapsed_hrs,
                    T.ITHD_ISMSIncidentResolution_Goal_hrs = S.ITHD_ISMSIncidentResolution_Goal_hrs,
                    T.ITHD_ISMSIncidentResolution_Breached = S.ITHD_ISMSIncidentResolution_Breached,
                    T.ITHD_ISMSIncidentResolution_Cycles = S.ITHD_ISMSIncidentResolution_Cycles,
                    T.ITHD_Resolution = S.ITHD_Resolution
                WHEN NOT MATCHED THEN INSERT (T, Project, Key, Summary, Status, Priority, Resolution, Created, Updated, Resolved, Reporter, Assignee, Component, RemedyTicketNumber, Links, {SR_REF_BQ_NAME}, SyncTime, TimeToFirstResponse_Elapsed_hrs, TimeToFirstResponse_Goal_hrs, TimeToFirstResponse_Breached, TimeToFirstResponse_Cycles, TimeToResolve_Elapsed_hrs, TimeToResolve_Goal_hrs, TimeToResolve_Breached, TimeToResolve_Cycles, TimeToResolution_Elapsed_hrs, TimeToResolution_Goal_hrs, TimeToResolution_Breached, TimeToResolution_Cycles, TimeToApproveNormalChange_Elapsed_hrs, TimeToApproveNormalChange_Goal_hrs, TimeToApproveNormalChange_Breached, TimeToApproveNormalChange_Cycles, ProlongCase_Elapsed_hrs, ProlongCase_Goal_hrs, ProlongCase_Breached, ProlongCase_Cycles, TimeToCloseAfterResolution_Elapsed_hrs, TimeToCloseAfterResolution_Goal_hrs, TimeToCloseAfterResolution_Breached, TimeToCloseAfterResolution_Cycles, AppSupEscalation, AssociatedTeam, TransactionStatus, Service, Origin, RootCause, ResolutionSecurity, Symptoms, StoryPoints, ITHD_TimeToFirstResponse_Elapsed_hrs, ITHD_TimeToFirstResponse_Goal_hrs, ITHD_TimeToFirstResponse_Breached, ITHD_TimeToFirstResponse_Cycles, ITHD_TimeToResolution_Elapsed_hrs, ITHD_TimeToResolution_Goal_hrs, ITHD_TimeToResolution_Breached, ITHD_TimeToResolution_Cycles, ITHD_ISMSIncidentResponse_Elapsed_hrs, ITHD_ISMSIncidentResponse_Goal_hrs, ITHD_ISMSIncidentResponse_Breached, ITHD_ISMSIncidentResponse_Cycles, ITHD_ISMSIncidentResolution_Elapsed_hrs, ITHD_ISMSIncidentResolution_Goal_hrs, ITHD_ISMSIncidentResolution_Breached, ITHD_ISMSIncidentResolution_Cycles, ITHD_Resolution) VALUES (S.T, S.Project, S.Key, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, IF(S.Component IS NULL, NULL, [S.Component]), IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]), S.Links, S.{SR_REF_BQ_NAME}, S.SyncTime, S.TimeToFirstResponse_Elapsed_hrs, S.TimeToFirstResponse_Goal_hrs, S.TimeToFirstResponse_Breached, S.TimeToFirstResponse_Cycles, S.TimeToResolve_Elapsed_hrs, S.TimeToResolve_Goal_hrs, S.TimeToResolve_Breached, S.TimeToResolve_Cycles, S.TimeToResolution_Elapsed_hrs, S.TimeToResolution_Goal_hrs, S.TimeToResolution_Breached, S.TimeToResolution_Cycles, S.TimeToApproveNormalChange_Elapsed_hrs, S.TimeToApproveNormalChange_Goal_hrs, S.TimeToApproveNormalChange_Breached, S.TimeToApproveNormalChange_Cycles, S.ProlongCase_Elapsed_hrs, S.ProlongCase_Goal_hrs, S.ProlongCase_Breached, S.ProlongCase_Cycles, S.TimeToCloseAfterResolution_Elapsed_hrs, S.TimeToCloseAfterResolution_Goal_hrs, S.TimeToCloseAfterResolution_Breached, S.TimeToCloseAfterResolution_Cycles, S.AppSupEscalation, S.AssociatedTeam, S.TransactionStatus, S.Service, S.Origin, S.RootCause, S.ResolutionSecurity, S.Symptoms, S.StoryPoints, S.ITHD_TimeToFirstResponse_Elapsed_hrs, S.ITHD_TimeToFirstResponse_Goal_hrs, S.ITHD_TimeToFirstResponse_Breached, S.ITHD_TimeToFirstResponse_Cycles, S.ITHD_TimeToResolution_Elapsed_hrs, S.ITHD_TimeToResolution_Goal_hrs, S.ITHD_TimeToResolution_Breached, S.ITHD_TimeToResolution_Cycles, S.ITHD_ISMSIncidentResponse_Elapsed_hrs, S.ITHD_ISMSIncidentResponse_Goal_hrs, S.ITHD_ISMSIncidentResponse_Breached, S.ITHD_ISMSIncidentResponse_Cycles, S.ITHD_ISMSIncidentResolution_Elapsed_hrs, S.ITHD_ISMSIncidentResolution_Goal_hrs, S.ITHD_ISMSIncidentResolution_Breached, S.ITHD_ISMSIncidentResolution_Cycles, S.ITHD_Resolution)
            '''
            client.query(merge_query).result()
            logging.info(f"Merged temp table into '{dataset_id}.{table_id}'.")
        except Exception as e:
            logging.error(f"Error merging temp table: {e}")

        delete_temp_table(client, dataset_id, temp_table_id)

        # Log pipeline end
        window_start_dt = observed_min_updated or jql_window_start
        window_end_dt = observed_max_updated or jql_window_end
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline finished",
            status="SUCCESS",
            window_start=window_start_dt,
            window_end=window_end_dt,
            rows_merged=issues_processed,
            duration_seconds=duration_seconds,
        )
    except Exception as e:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="ERROR",
            message=f"Exception: {e}",
            status="ERROR",
            error_code=getattr(e, "code", None),
            duration_seconds=duration_seconds,
        )
        raise


@functions_framework.http
def main(request):
    """Cloud Function HTTP entry point."""
    # Cleanup: Mark stale RUNNING entries as ERROR (older than 10 minutes)
    try:
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        cleanup_query = '''
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = 'GCP - JiraTickets'
            AND Status = 'RUNNING'
            AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")
    
    try:
        fetch_and_sync_jira_data()
        return {"status": "success", "message": "Jira tickets sync completed"}, 200
    except Exception as e:
        error_msg = f"Cloud Function failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        # Send error notification email
        send_error_email(error_msg)
        return {"status": "error", "message": str(e)}, 500
