"""
Cloud Function: Jira Tickets Nightly Sync
Nightly backfill of Jira ticket data routed via VPC; writes to BigQuery UAT.
"""
import requests
import json
import logging
import uuid
import time
import random
import os
import re
from datetime import datetime, timedelta, timezone
from google.cloud import bigquery, secretmanager
import functions_framework

# Import shared helper functions (files in same directory)
from jira_helpers import (
    load_base_jql, build_jql, convert_timestamp, create_or_replace_temp_table,
    delete_temp_table, wait_for_table, insert_rows_with_retry, table_exists,
    execute_bq_query_with_retry
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

setup_root_logging()

JITTER_MAX_SECONDS = 0.3
MIN_PROGRESS_WINDOW_SEC = 600  # 10 minutes to avoid thrashing tiny windows
MIN_WINDOW_HOURS = 1  # Skip windows smaller than 1 hour
OVERLAP_MINUTES = 10
MIN_START_ENV = os.environ.get('MIN_START', '2023-01-01T00:00:00Z')
MIN_START = datetime.fromisoformat(MIN_START_ENV.replace('Z', '+00:00'))
ENABLE_SOFT_DELETE_RECONCILIATION = os.environ.get('ENABLE_SOFT_DELETE_RECONCILIATION', '').strip().lower() == 'true'
MISSING_KEY_CATCHUP_PER_PROJECT = int(os.environ.get('MISSING_KEY_CATCHUP_PER_PROJECT', '50000'))
CACHE_BATCHED_FETCH_SIZE = int(os.environ.get('CACHE_BATCHED_FETCH_SIZE', '500'))  # Issues cached in each batch
CACHE_BATCH_DURATION_SEC = int(os.environ.get('CACHE_BATCH_DURATION_SEC', '120'))  # 2-minute window
MAX_RUN_SECONDS = int(os.environ.get('MAX_RUN_SECONDS', '3300'))  # Exit before 3600s hard timeout
RUNNING_STALE_MINUTES = int(os.environ.get('RUNNING_STALE_MINUTES', '70'))  # Auto-clean stale RUNNING rows sooner
BASE_WINDOW_DAYS = int(os.environ.get('BASE_WINDOW_DAYS', '1'))
BASE_WINDOW_HOURS = float(os.environ.get('BASE_WINDOW_HOURS', str(BASE_WINDOW_DAYS * 24)))
MIN_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MIN_ADAPTIVE_WINDOW_HOURS', '2'))
MAX_ADAPTIVE_WINDOW_HOURS = float(os.environ.get('MAX_ADAPTIVE_WINDOW_HOURS', '720'))
ADAPTIVE_TARGET_ROWS = int(os.environ.get('ADAPTIVE_TARGET_ROWS', '4000'))
ADAPTIVE_LOW_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_LOW_WATERMARK_ROWS', '800'))
ADAPTIVE_HIGH_WATERMARK_ROWS = int(os.environ.get('ADAPTIVE_HIGH_WATERMARK_ROWS', '12000'))

DEFAULT_PROJECTS = [
    'GS&O Data Analytics',
    'Customer Success Management',
    'GS&O Tool Automation',
    'GS&O Knowledge Consolidation',
    'TAC',
    'VOICE - CE',
    'IOT CE',
    'Console Application Support',
    'Console Connect Provisioning',
    'Global Service Delivery Team',
    'Transmission TX-CE',
    'Mobility SMS - CE',
    'Managed Security Services',
    'Sherbet',
    'Google Contact Center AI Solution',
    'QMS Documentation',
    'Operational Case Reviews',
    'IT Helpdesk',
    'Vendor Verification Team',
    'IPECR',
    'Internal Knowledge Management',
    'ITOPS',
    'GS&O Strategic Initiatives'
]

PROJECT_NAME_ALIASES = {
    'ITOPS': ['IT Operations'],
    'IPECR': ['IP Engineering Change Request Project'],
}

SERVICE_JIRA_ID = 'customfield_11350'
ORIGIN_JIRA_ID = 'customfield_11351'
ROOT_CAUSE_JIRA_ID = 'customfield_10775'
RESOLUTION_SECURITY_JIRA_ID = 'customfield_11349'
SYMPTOMS_JIRA_ID = 'customfield_11365'
ATTACK_JIRA_ID = 'customfield_15295'
FEATURE_TEAM_JIRA_ID = 'customfield_10780'
REMEDY_TICKET_MIGRATED_JIRA_ID = 'customfield_10647'
MAINTENANCE_WINDOW_START_JIRA_ID = 'customfield_10514'
MAINTENANCE_WINDOW_END_JIRA_ID = 'customfield_10515'
TIME_TO_FIRST_RESPONSE_JIRA_ID = 'customfield_10627'
TIME_TO_RESOLVE_JIRA_ID = 'customfield_10686'
TIME_TO_RESOLUTION_JIRA_ID = 'customfield_10668'
TIME_TO_APPROVE_NORMAL_CHANGE_JIRA_ID = 'customfield_10640'
PROLONG_CASE_JIRA_ID = 'customfield_10560'
TIME_TO_CLOSE_AFTER_RESOLUTION_JIRA_ID = 'customfield_10552'
APP_SUP_ESCALATION_JIRA_ID = 'customfield_11171'
STORY_POINTS_JIRA_ID = 'customfield_10347'
ITHD_ISMS_INCIDENT_RESPONSE_JIRA_ID = 'customfield_13449'
ITHD_ISMS_INCIDENT_RESOLUTION_JIRA_ID = 'customfield_13450'
ITHD_RESOLUTION_JIRA_ID = 'customfield_13448'
KNOWLEDGE_MANAGEMENT_JIRA_ID = 'customfield_15761'
DIRECTORY_INTERNAL_JIRA_ID = 'customfield_15827'
CONFLUENCE_URL_JIRA_ID = 'customfield_11184'
INCLUDE_CHILD_PAGES_JIRA_ID = 'customfield_15829'
VERIFIER_JIRA_ID = 'customfield_10674'
APPROVERS_JIRA_ID = 'customfield_10516'


def to_utc_aware(dt):
    if dt is None:
        return None
    if getattr(dt, 'tzinfo', None):
        try:
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def ensure_progress_table(client, dataset_id, table_id):
    schema = (
        "WindowStart TIMESTAMP, WindowEnd TIMESTAMP, Status STRING, "
        "LastRun TIMESTAMP, Project STRING, RowCount INT64"
    )
    client.query(
        f"CREATE TABLE IF NOT EXISTS `{dataset_id}.{table_id}` ({schema})"
    ).result()


def ensure_soft_delete_columns(client, dataset_id, table_id):
    """Ensure soft-delete and newly tracked custom-field columns exist on the target table."""
    table_ref = f"{client.project}.{dataset_id}.{table_id}"
    try:
        table = client.get_table(table_ref)
        existing_fields = {
            field.name: {
                'type': field.field_type.upper(),
                'mode': (field.mode or 'NULLABLE').upper(),
            }
            for field in table.schema
        }
    except Exception:
        existing_fields = {}
        existing_columns = set()

    existing_columns = set(existing_fields.keys())

    # Only issue DDL when the column is genuinely absent — avoids quota burns on every run.
    simple_columns = [
        ('IsDeleted', 'BOOL'),
        ('DeletedAt', 'TIMESTAMP'),
        ('AssociatedTeam', 'STRING'),
        ('TransactionStatus', 'STRING'),
        ('Service', 'STRING'),
        ('Origin', 'STRING'),
        ('RootCause', 'STRING'),
        ('ResolutionSecurity', 'STRING'),
        ('Symptoms', 'STRING'),
        ('ATTCK', 'STRING'),
        ('Description', 'STRING'),
        ('IssueId', 'STRING'),
        ('ReporterId', 'STRING'),
        ('AssigneeId', 'STRING'),
        ('DueDate', 'DATE'),
        ('FeatureTeam', 'STRING'),
        ('MaintenanceWindowStart', 'TIMESTAMP'),
        ('MaintenanceWindowEnd', 'TIMESTAMP'),
        ('KnowledgeManagement', 'STRING'),
        ('DirectoryInternal', 'STRING'),
        ('ConfluenceURL', 'STRING'),
        ('IncludeChildPages', 'STRING'),
        ('Verifier', 'STRING'),
        ('VerifierId', 'STRING'),
        ('Approvers', 'STRING'),
        ('ApproversId', 'STRING'),
        ('StoryPoints', 'INT64'),
        ('TimeSpentSeconds', 'INT64'),
        ('TimeToFirstResponse_Elapsed_hrs', 'FLOAT64'),
        ('TimeToFirstResponse_Goal_hrs', 'FLOAT64'),
        ('TimeToFirstResponse_Breached', 'BOOL'),
        ('TimeToFirstResponse_Cycles', 'INT64'),
        ('TimeToResolve_Elapsed_hrs', 'FLOAT64'),
        ('TimeToResolve_Goal_hrs', 'FLOAT64'),
        ('TimeToResolve_Breached', 'BOOL'),
        ('TimeToResolve_Cycles', 'INT64'),
        ('TimeToResolution_Elapsed_hrs', 'FLOAT64'),
        ('TimeToResolution_Goal_hrs', 'FLOAT64'),
        ('TimeToResolution_Breached', 'BOOL'),
        ('TimeToResolution_Cycles', 'INT64'),
        ('TimeToApproveNormalChange_Elapsed_hrs', 'FLOAT64'),
        ('TimeToApproveNormalChange_Goal_hrs', 'FLOAT64'),
        ('TimeToApproveNormalChange_Breached', 'BOOL'),
        ('TimeToApproveNormalChange_Cycles', 'INT64'),
        ('ProlongCase_Elapsed_hrs', 'FLOAT64'),
        ('ProlongCase_Goal_hrs', 'FLOAT64'),
        ('ProlongCase_Breached', 'BOOL'),
        ('ProlongCase_Cycles', 'INT64'),
        ('TimeToCloseAfterResolution_Elapsed_hrs', 'FLOAT64'),
        ('TimeToCloseAfterResolution_Goal_hrs', 'FLOAT64'),
        ('TimeToCloseAfterResolution_Breached', 'BOOL'),
        ('TimeToCloseAfterResolution_Cycles', 'INT64'),
        ('ITHD_TimeToFirstResponse_Elapsed_hrs', 'FLOAT64'),
        ('ITHD_TimeToFirstResponse_Goal_hrs', 'FLOAT64'),
        ('ITHD_TimeToFirstResponse_Breached', 'BOOL'),
        ('ITHD_TimeToFirstResponse_Cycles', 'INT64'),
        ('ITHD_TimeToResolution_Elapsed_hrs', 'FLOAT64'),
        ('ITHD_TimeToResolution_Goal_hrs', 'FLOAT64'),
        ('ITHD_TimeToResolution_Breached', 'BOOL'),
        ('ITHD_TimeToResolution_Cycles', 'INT64'),
        ('ITHD_ISMSIncidentResponse_Elapsed_hrs', 'FLOAT64'),
        ('ITHD_ISMSIncidentResponse_Goal_hrs', 'FLOAT64'),
        ('ITHD_ISMSIncidentResponse_Breached', 'BOOL'),
        ('ITHD_ISMSIncidentResponse_Cycles', 'INT64'),
        ('ITHD_ISMSIncidentResolution_Elapsed_hrs', 'FLOAT64'),
        ('ITHD_ISMSIncidentResolution_Goal_hrs', 'FLOAT64'),
        ('ITHD_ISMSIncidentResolution_Breached', 'BOOL'),
        ('ITHD_ISMSIncidentResolution_Cycles', 'INT64'),
        ('ITHD_Resolution', 'STRING'),
        ('AppSupEscalation', 'STRING'),
    ]
    for col_name, col_type in simple_columns:
        if col_name not in existing_columns:
            client.query(
                f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ).result()
            logging.info(f"Added missing column {col_name} to {table_id}")

    labels_field = existing_fields.get('Labels')
    if labels_field is None:
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Labels ARRAY<STRING>"
        ).result()
    elif labels_field['type'] == 'STRING' and labels_field['mode'] != 'REPEATED':
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Labels_array ARRAY<STRING>"
        ).result()
        client.query(
            f"""
            UPDATE `{dataset_id}.{table_id}`
            SET Labels_array = COALESCE(
                Labels_array,
                ARRAY(
                    SELECT TRIM(label)
                    FROM UNNEST(SPLIT(Labels, ',')) AS label
                    WHERE TRIM(label) != ''
                )
            )
            WHERE Labels IS NOT NULL
            """
        ).result()
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` DROP COLUMN Labels"
        ).result()
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` RENAME COLUMN Labels_array TO Labels"
        ).result()

    attachment_field = existing_fields.get('Attachment')
    if attachment_field is None:
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Attachment JSON"
        ).result()
    elif attachment_field['type'] == 'STRING' and attachment_field['mode'] != 'REPEATED':
        # One-time in-place migration from STRING to JSON while preserving non-JSON raw payloads.
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS Attachment_json JSON"
        ).result()
        client.query(
            f"""
            UPDATE `{dataset_id}.{table_id}`
            SET Attachment_json = COALESCE(
                Attachment_json,
                SAFE.PARSE_JSON(Attachment),
                TO_JSON(STRUCT(Attachment AS raw))
            )
            WHERE Attachment IS NOT NULL
            """
        ).result()
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` DROP COLUMN Attachment"
        ).result()
        client.query(
            f"ALTER TABLE `{dataset_id}.{table_id}` RENAME COLUMN Attachment_json TO Attachment"
        ).result()

    if 'TranscationStatus' in existing_columns:
        client.query(
            f"""
            UPDATE `{dataset_id}.{table_id}`
            SET TransactionStatus = COALESCE(TransactionStatus, TranscationStatus)
            WHERE TranscationStatus IS NOT NULL
            """
        ).result()


def _to_sql_string_list(values):
    escaped = []
    for value in values:
        escaped.append("'" + str(value).replace("'", "''") + "'")
    return ", ".join(escaped)


def get_project_name_variants(project):
    variants = [project]
    for alias in PROJECT_NAME_ALIASES.get(project, []):
        if alias not in variants:
            variants.append(alias)
    return variants


def get_project_filter_sql(project, column_name='Project'):
    variants = get_project_name_variants(project)
    return f"{column_name} IN ({_to_sql_string_list(variants)})"


def get_known_project_keys(client, dataset_id, table_id, project):
    """Return known non-empty keys already present in BQ for a project."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter('project_names', 'STRING', get_project_name_variants(project)),
        ]
    )
    rows = client.query(
        f"""
        SELECT DISTINCT Key
        FROM `{dataset_id}.{table_id}`
        WHERE Project IN UNNEST(@project_names)
          AND Key IS NOT NULL
          AND TRIM(Key) <> ''
        """,
        job_config=job_config,
    ).result()
    return {r.Key for r in rows if getattr(r, 'Key', None)}


def get_recent_window_metrics(client, dataset_id, table_id, project, sample_size=5):
    """Return recent complete windows for adaptive sizing."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('p', 'STRING', project),
            bigquery.ScalarQueryParameter('n', 'INT64', int(sample_size)),
        ]
    )
    rows = client.query(
        f"""
        SELECT
          RowCount,
          TIMESTAMP_DIFF(WindowEnd, WindowStart, SECOND) AS WindowSeconds
        FROM `{dataset_id}.{table_id}`
        WHERE Project=@p
          AND Status='complete'
          AND RowCount IS NOT NULL
          AND WindowEnd > WindowStart
        ORDER BY LastRun DESC
        LIMIT @n
        """,
        job_config=job_config,
    ).result()

    metrics = []
    for r in rows:
        try:
            rc = int(r.RowCount)
            sec = int(r.WindowSeconds)
            if sec > 0:
                metrics.append((rc, sec))
        except Exception:
            continue
    return metrics


def choose_window_hours(client, dataset_id, table_id, project):
    """Choose next window size using recent rows-per-hour density."""
    min_hours = max(MIN_ADAPTIVE_WINDOW_HOURS, 1.0)
    max_hours = max(MAX_ADAPTIVE_WINDOW_HOURS, min_hours)
    base_hours = min(max(BASE_WINDOW_HOURS, min_hours), max_hours)

    metrics = get_recent_window_metrics(client, dataset_id, table_id, project)
    if not metrics:
        logging.info(f"Adaptive window bootstrap (default): {base_hours:.2f}h")
        return base_hours

    total_rows = sum(rc for rc, _ in metrics)
    total_hours = sum(sec for _, sec in metrics) / 3600.0
    rows_per_hour = (total_rows / total_hours) if total_hours > 0 else 0.0
    last_rows = metrics[0][0]

    if rows_per_hour <= 0:
        adaptive_hours = max_hours
    else:
        adaptive_hours = ADAPTIVE_TARGET_ROWS / rows_per_hour

    if last_rows >= ADAPTIVE_HIGH_WATERMARK_ROWS:
        adaptive_hours *= 0.5
    elif last_rows <= ADAPTIVE_LOW_WATERMARK_ROWS:
        adaptive_hours *= 1.5

    adaptive_hours = min(max(adaptive_hours, min_hours), max_hours)
    logging.info(
        "Adaptive window chosen for %s: %.2fh (rows_per_hour=%.2f, last_rows=%s, sample=%s)",
        project,
        adaptive_hours,
        rows_per_hour,
        last_rows,
        len(metrics),
    )
    return adaptive_hours


def select_window(client, dataset_id, table_id, project):
    now = datetime.now(timezone.utc)
    ws = None
    we = None
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('p', 'STRING', project)]
    )
    try:
        res = client.query(
            f"SELECT WindowStart, WindowEnd FROM `{dataset_id}.{table_id}` "
            "WHERE Project=@p AND Status NOT IN ('complete','degraded') "
            "ORDER BY WindowStart ASC LIMIT 1",
            job_config=job_config,
        ).result()
        for r in res:
            ws = r.WindowStart
            we = r.WindowEnd
            break
    except Exception:
        pass

    if ws and we:
        return to_utc_aware(ws), to_utc_aware(we)

    latest = None
    try:
        res = client.query(
            f"SELECT WindowEnd FROM `{dataset_id}.{table_id}` "
            "WHERE Project=@p ORDER BY WindowEnd DESC LIMIT 1",
            job_config=job_config,
        ).result()
        for r in res:
            latest = r.WindowEnd
            break
    except Exception:
        pass

    if latest:
        latest = to_utc_aware(latest)
        # Check if we're too close to now to create a meaningful window
        hours_from_latest = (now - latest).total_seconds() / 3600.0
        if hours_from_latest < MIN_WINDOW_HOURS:
            # Return None to signal no window available
            return None, None
        start = latest - timedelta(minutes=OVERLAP_MINUTES)
    else:
        start = MIN_START

    window_hours = choose_window_hours(client, dataset_id, table_id, project)
    end = start + timedelta(hours=window_hours)
    end = min(end, now)

    # Final check: if resulting window is too small, return None
    try:
        if (end - start).total_seconds() / 3600.0 < MIN_WINDOW_HOURS:
            return None, None
    except Exception:
        pass

    return start, end


def mark_progress(client, dataset_id, table_id, project, ws, we, status, row_count=None):
    rc_val = 'NULL' if row_count is None else row_count
    ws_str = to_utc_aware(ws).strftime('%Y-%m-%d %H:%M:%S') if ws else None
    we_str = to_utc_aware(we).strftime('%Y-%m-%d %H:%M:%S') if we else None
    client.query(
        f"""
        MERGE `{dataset_id}.{table_id}` T
        USING (SELECT TIMESTAMP('{ws_str}') AS WindowStart, TIMESTAMP('{we_str}') AS WindowEnd, '{project}' AS Project) S
        ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project
        WHEN MATCHED THEN UPDATE SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc_val}, Project=S.Project
        WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project,RowCount)
        VALUES (S.WindowStart,S.WindowEnd,'{status}',CURRENT_TIMESTAMP(),S.Project,{rc_val})
        """
    ).result()


def get_secret(secret_id, project_id="pccw-internal-virtual-agent"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')


def insert_rows_resilient(client, dataset_id, temp_table_id, rows, bq_schema, max_attempts=3):
    """Insert rows with resilience: retry, and recreate temp table if needed."""
    if not rows:
        return True
    
    for attempt in range(max_attempts):
        # First, try to insert using the standard retry logic
        if insert_rows_with_retry(client, dataset_id, temp_table_id, rows, bq_schema, retries=5, delay=3):
            return True
        
        # If insert failed, check if table still exists; if not, recreate and retry
        if not table_exists(client, dataset_id, temp_table_id):
            logging.warning(f"Temp table missing after failed insert attempt {attempt + 1}/{max_attempts}. Recreating...")
            if create_or_replace_temp_table(client, dataset_id, temp_table_id, bq_schema):
                if wait_for_table(client, dataset_id, temp_table_id, retries=15, delay=1):
                    # Retry insert after recreation
                    if insert_rows_with_retry(client, dataset_id, temp_table_id, rows, bq_schema, retries=5, delay=3):
                        return True
        
        if attempt < max_attempts - 1:
            time.sleep(2 * (1.5 ** attempt))
    
    logging.error(f"Failed to insert rows after {max_attempts} resilient attempts")
    return False


def load_config():
    try:
        api_token = get_secret("jira-api-token")
        user_email = get_secret("jira-user-email")
        return {"jira_api_token": api_token, "jira_user": user_email}
    except Exception as e:
        logging.error(f"Failed to load config from Secret Manager: {e}")
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


def resolve_account_id_display_name(account_id, auth, cache):
    """Resolve Jira accountId to display name with in-run caching."""
    if not account_id:
        return None
    if account_id in cache:
        return cache[account_id]

    try:
        user_url = "https://consoleconnect.atlassian.net/rest/api/3/user"
        response = requests.get(user_url, auth=auth, params={"accountId": account_id}, timeout=20)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 30) or 30)
            time.sleep(retry_after + random.uniform(0, JITTER_MAX_SECONDS))
            response = requests.get(user_url, auth=auth, params={"accountId": account_id}, timeout=20)
        response.raise_for_status()
        display_name = (response.json() or {}).get('displayName')
        cache[account_id] = display_name
        return display_name
    except Exception:
        cache[account_id] = None
        return None


def extract_user_names_and_ids(field_value, auth=None, cache=None):
    """Extract comma-separated user display names and account IDs from Jira user picker fields."""
    if field_value is None:
        return None, None

    values = field_value if isinstance(field_value, list) else [field_value]
    names = []
    ids = []

    for item in values:
        account_id = None
        display_name = None

        if isinstance(item, dict):
            account_id = item.get('accountId') or item.get('id')
            display_name = item.get('displayName') or item.get('name')
        elif isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            account_id = text

        if account_id and account_id not in ids:
            ids.append(account_id)

        if not display_name and account_id and auth and cache is not None:
            display_name = resolve_account_id_display_name(account_id, auth, cache)

        if display_name and display_name not in names:
            names.append(display_name)

    names_csv = ', '.join(names) if names else None
    ids_csv = ', '.join(ids) if ids else None
    return names_csv, ids_csv


def extract_adf_text(adf_node):
    """Extract plain text from Jira ADF nodes."""
    if adf_node is None:
        return None
    if isinstance(adf_node, str):
        return adf_node
    if isinstance(adf_node, list):
        parts = [extract_adf_text(item) for item in adf_node]
        text = " ".join([p for p in parts if p])
        return text.strip() or None
    if not isinstance(adf_node, dict):
        return str(adf_node)

    if adf_node.get("type") == "text":
        return adf_node.get("text")

    content = adf_node.get("content")
    if isinstance(content, list):
        parts = [extract_adf_text(item) for item in content]
        text = " ".join([p for p in parts if p])
        return text.strip() or None

    return None


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
    if not remedy_ticket_number:
        return []
    return re.findall(r'INC\d{9,}', str(remedy_ticket_number))


def extract_sla_metrics(sla_field):
    """Extract elapsed hours, goal hours, breached flag and cycle count from Jira SLA field."""
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


def build_ticket_row(issue, sr_ref_jira_id, sr_ref_bq_name, auth=None, account_name_cache=None):
    if not issue:
        return None
    key = issue.get('key')
    if not key or not str(key).strip():
        return None
    fields = issue.get('fields', {})
    labels = [label.strip() for label in fields.get('labels', []) if str(label).strip()]
    verifier_name, verifier_id = extract_user_names_and_ids(
        fields.get(VERIFIER_JIRA_ID),
        auth=auth,
        cache=account_name_cache,
    )
    approver_names, approver_ids = extract_user_names_and_ids(
        fields.get(APPROVERS_JIRA_ID),
        auth=auth,
        cache=account_name_cache,
    )

    sla_fields = {
        'TimeToFirstResponse': fields.get(TIME_TO_FIRST_RESPONSE_JIRA_ID),
        'TimeToResolve': fields.get(TIME_TO_RESOLVE_JIRA_ID),
        'TimeToResolution': fields.get(TIME_TO_RESOLUTION_JIRA_ID),
        'TimeToApproveNormalChange': fields.get(TIME_TO_APPROVE_NORMAL_CHANGE_JIRA_ID),
        'ProlongCase': fields.get(PROLONG_CASE_JIRA_ID),
        'TimeToCloseAfterResolution': fields.get(TIME_TO_CLOSE_AFTER_RESOLUTION_JIRA_ID),
        'ITHD_TimeToFirstResponse': fields.get(TIME_TO_FIRST_RESPONSE_JIRA_ID),
        'ITHD_TimeToResolution': fields.get(TIME_TO_RESOLUTION_JIRA_ID),
        'ITHD_ISMSIncidentResponse': fields.get(ITHD_ISMS_INCIDENT_RESPONSE_JIRA_ID),
        'ITHD_ISMSIncidentResolution': fields.get(ITHD_ISMS_INCIDENT_RESOLUTION_JIRA_ID),
    }

    sla_metrics = {}
    for k, v in sla_fields.items():
        elapsed, goal, breached, cycles = extract_sla_metrics(v)
        sla_metrics[f'{k}_Elapsed'] = elapsed
        sla_metrics[f'{k}_Goal'] = goal
        sla_metrics[f'{k}_Breached'] = breached
        sla_metrics[f'{k}_Cycles'] = cycles

    story_points = None
    raw_story_points = get_field_value(fields.get(STORY_POINTS_JIRA_ID))
    if raw_story_points is not None:
        try:
            story_points = int(float(raw_story_points))
        except Exception:
            story_points = None

    row = {
        "T": fields.get('issuetype', {}).get('name'),
        "Project": fields.get('project', {}).get('name'),
        "Key": key,
        "IssueId": issue.get('id'),
        "Summary": fields.get('summary'),
        "Status": fields.get('status', {}).get('name'),
        "Created": convert_timestamp(fields.get('created')),
        "Updated": convert_timestamp(fields.get('updated')),
        "Resolved": convert_timestamp(fields.get('resolutiondate')),
        "DueDate": fields.get('duedate'),
        "Reporter": get_field_value(fields.get('reporter')),
        "ReporterId": (fields.get('reporter') or {}).get('accountId') if isinstance(fields.get('reporter'), dict) else None,
        "Assignee": get_field_value(fields.get('assignee')),
        "AssigneeId": (fields.get('assignee') or {}).get('accountId') if isinstance(fields.get('assignee'), dict) else None,
        "Component": ', '.join([get_field_value(component) for component in fields.get('components', [])]) if fields.get('components') else None,
        "FeatureTeam": get_field_value(fields.get(FEATURE_TEAM_JIRA_ID)),
        "MaintenanceWindowStart": convert_timestamp(fields.get(MAINTENANCE_WINDOW_START_JIRA_ID)),
        "MaintenanceWindowEnd": convert_timestamp(fields.get(MAINTENANCE_WINDOW_END_JIRA_ID)),
        "KnowledgeManagement": get_field_value(fields.get(KNOWLEDGE_MANAGEMENT_JIRA_ID)),
        "DirectoryInternal": get_field_value(fields.get(DIRECTORY_INTERNAL_JIRA_ID)),
        "ConfluenceURL": get_field_value(fields.get(CONFLUENCE_URL_JIRA_ID)),
        "IncludeChildPages": get_field_value(fields.get(INCLUDE_CHILD_PAGES_JIRA_ID)),
        "Verifier": verifier_name,
        "VerifierId": verifier_id,
        "Approvers": approver_names,
        "ApproversId": approver_ids,
        "RemedyTicketNumber": ', '.join(extract_incident_numbers(get_field_value(fields.get(REMEDY_TICKET_MIGRATED_JIRA_ID)) or get_field_value(fields.get('customfield_10088')))) or get_field_value(fields.get(REMEDY_TICKET_MIGRATED_JIRA_ID)) or get_field_value(fields.get('customfield_10088')),
        "Links": extract_issue_links(fields.get('issuelinks')),
        "Description": extract_adf_text(fields.get('description')),
        "Attachment": json.dumps(fields.get('attachment')) if fields.get('attachment') else None,
        sr_ref_bq_name: get_field_value(fields.get(sr_ref_jira_id)),
        "AssociatedTeam": get_field_value(fields.get('customfield_11134')),
        "TransactionStatus": get_field_value(fields.get('customfield_11170')),
        "Service": get_field_value(fields.get(SERVICE_JIRA_ID)),
        "Origin": get_field_value(fields.get(ORIGIN_JIRA_ID)),
        "RootCause": get_field_value(fields.get(ROOT_CAUSE_JIRA_ID)),
        "ResolutionSecurity": get_field_value(fields.get(RESOLUTION_SECURITY_JIRA_ID)),
        "Symptoms": get_field_value(fields.get(SYMPTOMS_JIRA_ID)),
        "ATTCK": get_field_value(fields.get(ATTACK_JIRA_ID)),
        "StoryPoints": story_points,
        "TimeSpentSeconds": fields.get('timetracking', {}).get('timeSpentSeconds') if isinstance(fields.get('timetracking'), dict) else fields.get('timespent'),
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
        "ITHD_Resolution": get_field_value(fields.get(ITHD_RESOLUTION_JIRA_ID)),
        "AppSupEscalation": get_field_value(fields.get(APP_SUP_ESCALATION_JIRA_ID)),
        "Priority": get_field_value(fields.get('priority')),
        "Resolution": get_field_value(fields.get('resolution')),
        "SyncTime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
    }

    if labels:
        row["Labels"] = labels

    return row


def fetch_and_sync_jira_tickets_nightly():
    config = load_config()
    if config is None:
        return

    jira_url = 'https://consoleconnect.atlassian.net/rest/api/3/search/jql'
    username = config.get('jira_user') or config.get('jira_user_email') or 'jjkli@consoleconnect.com'
    api_token = config.get('jira_api_token')

    SR_REF_JIRA_ID = 'customfield_10382'
    SR_REF_BQ_NAME = 'SR_Ref'
    ASSOCIATED_TEAM_JIRA_ID = 'customfield_11134'
    TRANSACTION_STATUS_JIRA_ID = 'customfield_11170'

    table_id = 'JiraTickets'
    temp_table_id = 'JiraTickets_temp'
    progress_table_id = 'JiraTickets_progress'
    pipeline_name = "GCP - JiraTicketsNightly"

    run_id = str(uuid.uuid4())
    client = None
    run_started = None
    temp_table_id_run = None
    total_rows_merged = 0
    final_status = "ERROR"
    final_level = "ERROR"
    final_message = "Pipeline did not complete"
    final_error_code = None
    run_had_errors = False

    try:
        run_started = datetime.now(timezone.utc)

        # Write to UAT BigQuery
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        dataset_id = 'GSO'

        log_pipeline_run(client, pipeline_name=pipeline_name, run_id=run_id, level="INFO", message="Pipeline started", status="RUNNING")

        ensure_progress_table(client, dataset_id, progress_table_id)
        projects = DEFAULT_PROJECTS
        env_single = os.environ.get('SINGLE_PROJECT') or os.environ.get('PROJECT')
        env_projects = os.environ.get('PROJECTS')
        if env_single:
            projects = [env_single.strip()]
        elif env_projects:
            projects = [p.strip() for p in env_projects.split(',') if p.strip()]
        logging.info(f"Projects for nightly run: {projects}")

        # Schema aligned with hourly tickets
        bq_schema = [
            bigquery.SchemaField("T", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Project", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("IssueId", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Summary", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Priority", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Resolution", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Resolved", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("DueDate", "DATE", mode="NULLABLE"),
            bigquery.SchemaField("Reporter", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ReporterId", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Assignee", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("AssigneeId", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Component", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("FeatureTeam", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("MaintenanceWindowStart", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("MaintenanceWindowEnd", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("KnowledgeManagement", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("DirectoryInternal", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ConfluenceURL", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("IncludeChildPages", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Verifier", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("VerifierId", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Approvers", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ApproversId", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RemedyTicketNumber", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Links", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Description", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Labels", "STRING", mode="REPEATED"),
            bigquery.SchemaField("Attachment", "JSON", mode="NULLABLE"),
            bigquery.SchemaField(SR_REF_BQ_NAME, "STRING", mode="NULLABLE"),
            bigquery.SchemaField("AssociatedTeam", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("TransactionStatus", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Service", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Origin", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("RootCause", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ResolutionSecurity", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Symptoms", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("ATTCK", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("StoryPoints", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("TimeSpentSeconds", "INT64", mode="NULLABLE"),
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
            bigquery.SchemaField("AppSupEscalation", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
        ]

        try:
            ensure_soft_delete_columns(client, dataset_id, table_id)
        except Exception as _schema_err:
            logging.warning(f"ensure_soft_delete_columns non-fatal error (columns likely exist): {_schema_err}")

        ticket_search_fields = [
            'key',
            'issuetype',
            'project',
            'summary',
            'status',
            'created',
            'updated',
            'resolutiondate',
            'duedate',
            'reporter',
            'assignee',
            'components',
            'priority',
            'resolution',
            'issuelinks',
            'description',
            'labels',
            'attachment',
            'customfield_10088',
            SR_REF_JIRA_ID,
            ASSOCIATED_TEAM_JIRA_ID,
            TRANSACTION_STATUS_JIRA_ID,
            SERVICE_JIRA_ID,
            ORIGIN_JIRA_ID,
            ROOT_CAUSE_JIRA_ID,
            RESOLUTION_SECURITY_JIRA_ID,
            SYMPTOMS_JIRA_ID,
            ATTACK_JIRA_ID,
            TIME_TO_FIRST_RESPONSE_JIRA_ID,
            TIME_TO_RESOLVE_JIRA_ID,
            TIME_TO_RESOLUTION_JIRA_ID,
            TIME_TO_APPROVE_NORMAL_CHANGE_JIRA_ID,
            PROLONG_CASE_JIRA_ID,
            TIME_TO_CLOSE_AFTER_RESOLUTION_JIRA_ID,
            APP_SUP_ESCALATION_JIRA_ID,
            STORY_POINTS_JIRA_ID,
            ITHD_ISMS_INCIDENT_RESPONSE_JIRA_ID,
            ITHD_ISMS_INCIDENT_RESOLUTION_JIRA_ID,
            ITHD_RESOLUTION_JIRA_ID,
            FEATURE_TEAM_JIRA_ID,
            REMEDY_TICKET_MIGRATED_JIRA_ID,
            MAINTENANCE_WINDOW_START_JIRA_ID,
            MAINTENANCE_WINDOW_END_JIRA_ID,
            KNOWLEDGE_MANAGEMENT_JIRA_ID,
            DIRECTORY_INTERNAL_JIRA_ID,
            CONFLUENCE_URL_JIRA_ID,
            INCLUDE_CHILD_PAGES_JIRA_ID,
            VERIFIER_JIRA_ID,
            APPROVERS_JIRA_ID,
            'timetracking',
        ]

        account_name_cache = {}
        auth = (username, api_token)

        def search_issues(jql: str, label: str, fields):
            headers_local = {'Accept': 'application/json'}
            auth_local = (username, api_token)
            start_at = 0
            max_results = 100
            all_issues = []
            had_error = False
            fields_param = ','.join(fields)
            attempts = 0

            while True:
                try:
                    params_local = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': fields_param}
                    resp = requests.get(jira_url, headers=headers_local, auth=auth_local, params=params_local, timeout=30)
                    if resp.status_code == 429:
                        ra = int(resp.headers.get('Retry-After', 30) or 30)
                        logging.warning(f"429 {label} search; sleeping {ra}s")
                        time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                        continue
                    resp.raise_for_status()
                    data_local = resp.json()
                    issues_local = data_local.get('issues', [])
                    total = data_local.get('total', 0)
                    all_issues.extend(issues_local)
                    start_at += len(issues_local)
                    attempts = 0 # Reset attempts on success
                    if start_at >= total or not issues_local:
                        break
                except Exception as e:
                    attempts += 1
                    if attempts >= 5:
                        had_error = True
                        logging.error(f"{label} pass error: {e}")
                        break
                    back = min(60, 2 ** attempts) + random.uniform(0, JITTER_MAX_SECONDS)
                    logging.warning(f"{label} pass error: {e}. Retrying ({attempts}/5) after {back:.1f}s")
                    time.sleep(back)

            logging.info(f"{label} pass fetched {len(all_issues)} issues")
            return all_issues, had_error

        def search_issue_keys(jql: str, label: str):
            issues, had_error = search_issues(jql, label, ['key'])
            keys = [issue.get('key') for issue in issues if issue.get('key')]
            logging.info(f"{label} pass fetched {len(keys)} issue keys")
            return keys, had_error

        def fetch_ticket_rows_for_keys(issue_keys, label):
            if not issue_keys:
                return []
            rows = []
            chunk_size = 50
            for index in range(0, len(issue_keys), chunk_size):
                key_chunk = issue_keys[index:index + chunk_size]
                keys_jql = ', '.join([f'"{key}"' for key in key_chunk if key])
                if not keys_jql:
                    continue
                chunk_jql = f"key in ({keys_jql})"
                issues, had_error = search_issues(chunk_jql, f"{label}:chunk{index // chunk_size + 1}", ticket_search_fields)
                if had_error:
                    logging.warning(f"{label} bulk fetch had Jira search errors for chunk {index // chunk_size + 1}")
                for issue in issues:
                    row = build_ticket_row(
                        issue,
                        SR_REF_JIRA_ID,
                        SR_REF_BQ_NAME,
                        auth=auth,
                        account_name_cache=account_name_cache,
                    )
                    if row:
                        rows.append(row)
            return rows

        def time_budget_reached():
            if not run_started:
                return False
            return (datetime.now(timezone.utc) - run_started).total_seconds() >= MAX_RUN_SECONDS

        def fetch_and_insert_ticket_rows_batched(issue_keys, label, dataset_id_inner, temp_table_id_inner, bq_schema_inner, stop_checker=None):
            """
            Fetch and insert ticket rows in batches to minimize memory usage.
            Processes keys in CACHE_BATCHED_FETCH_SIZE chunks, fetching and inserting each batch.
            Returns total count inserted.
            """
            if not issue_keys:
                return 0
            
            total_inserted = 0
            batch_start_idx = 0
            
            while batch_start_idx < len(issue_keys):
                if stop_checker and stop_checker():
                    logging.warning(f"{label}: stopping early due to runtime budget")
                    break
                batch_end_idx = min(batch_start_idx + CACHE_BATCHED_FETCH_SIZE, len(issue_keys))
                batch_keys = issue_keys[batch_start_idx:batch_end_idx]
                
                logging.debug(f"{label}: Processing batch {batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1} "
                            f"({len(batch_keys)} keys, indices {batch_start_idx}-{batch_end_idx})")
                
                # Fetch rows for this batch
                batch_rows = []
                chunk_size = 50
                for chunk_idx in range(0, len(batch_keys), chunk_size):
                    key_chunk = batch_keys[chunk_idx:chunk_idx + chunk_size]
                    keys_jql = ', '.join([f'"{key}"' for key in key_chunk if key])
                    if not keys_jql:
                        continue
                    chunk_jql = f"key in ({keys_jql})"
                    issues, had_error = search_issues(chunk_jql, 
                                                    f"{label}:batch{batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}"
                                                    f":chunk{chunk_idx // chunk_size + 1}", 
                                                    ticket_search_fields)
                    if had_error:
                        logging.warning(f"{label} had Jira search errors for batch chunk")
                    for issue in issues:
                        row = build_ticket_row(
                            issue,
                            SR_REF_JIRA_ID,
                            SR_REF_BQ_NAME,
                            auth=auth,
                            account_name_cache=account_name_cache,
                        )
                        if row:
                            batch_rows.append(row)
                
                # Insert this batch
                if batch_rows:
                    if insert_rows_resilient(client, dataset_id_inner, temp_table_id_inner, batch_rows, bq_schema_inner):
                        total_inserted += len(batch_rows)
                        logging.info(f"{label}: Inserted {len(batch_rows)} rows from batch "
                                   f"{batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}")
                    else:
                        logging.error(f"{label}: Failed to insert batch {batch_start_idx // CACHE_BATCHED_FETCH_SIZE + 1}")
                        return total_inserted  # Return what we've inserted so far; let caller retry
                
                batch_start_idx = batch_end_idx
            
            return total_inserted

        # Use single temp table with run_id suffix for all projects
        temp_table_id_run = f"{temp_table_id}_{run_id.replace('-', '_')[:8]}"

        # Clean up orphaned temp tables from previous crashed runs (older than 2h)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
            for tbl in client.list_tables(f"{client.project}.{dataset_id}"):
                if tbl.table_id.startswith(temp_table_id + '_') and tbl.table_id != temp_table_id_run:
                    tbl_ref = client.get_table(f"{dataset_id}.{tbl.table_id}")
                    if tbl_ref.created.replace(tzinfo=timezone.utc) < cutoff:
                        client.delete_table(tbl_ref, not_found_ok=True)
                        logging.info(f"Cleaned up orphaned temp table: {tbl.table_id}")
        except Exception as _cleanup_ex:
            logging.warning(f"Orphan temp table cleanup failed (non-fatal): {_cleanup_ex}")

        # Create temp table once for all projects
        if not create_or_replace_temp_table(client, dataset_id, temp_table_id_run, bq_schema):
            logging.error("Failed to create temp table for run.")
            raise Exception("Could not create temp table")
        if not wait_for_table(client, dataset_id, temp_table_id_run, retries=30, delay=2):
            logging.error("Temp table not available after extended wait.")
            raise Exception("Temp table not available")

        budget_reached = False
        
        for proj in projects:
            if time_budget_reached():
                logging.warning("Runtime budget reached before next project; ending run early")
                budget_reached = True
                break

            logging.info(f"Starting nightly window selection for project {proj}")
            project_current_keys = set()
            proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            project_filter_sql = get_project_filter_sql(proj)
            
            while True:
                if time_budget_reached():
                    logging.warning(f"Runtime budget reached while processing {proj}; ending run early")
                    budget_reached = True
                    break

                ws, we = select_window(client, dataset_id, progress_table_id, proj)
                if not ws or not we:
                    logging.info(f"No further window for {proj} (too close to now or complete)")
                    break
                now = datetime.now(timezone.utc)
                if ws >= now:
                    logging.info(f"Window start >= now; stopping {proj}")
                    break
                mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'in_progress')
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="INFO",
                    message="Window in_progress",
                    status="RUNNING",
                    window_start=ws.strftime('%Y-%m-%d %H:%M:%S'),
                    window_end=we.strftime('%Y-%m-%d %H:%M:%S'),
                )

                time_clause = f"updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                resolved_clause = f"resolutiondate >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND resolutiondate < \"{we.strftime('%Y/%m/%d %H:%M')}\""
                # Combined JQL - single search instead of two
                jql_combined = f"({proj_clause}) AND (({time_clause}) OR ({resolved_clause}))"
                logging.info(f"JQL combined window: {jql_combined}")

                rows_to_insert = []
                combined_issues, combined_had_error = search_issues(jql_combined, 'combined', ticket_search_fields)
                if combined_had_error:
                    logging.warning(f"Skipping window for project {proj} due to Jira search errors")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'degraded', row_count=0)
                    run_had_errors = True
                    break
                seen_keys = set()
                for issue in combined_issues:
                    key = issue.get('key')
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    project_current_keys.add(key)
                    row = build_ticket_row(
                        issue,
                        SR_REF_JIRA_ID,
                        SR_REF_BQ_NAME,
                        auth=auth,
                        account_name_cache=account_name_cache,
                    )
                    if row:
                        rows_to_insert.append(row)
                logging.info(f"Distinct issue keys to detail fetch: {len(seen_keys)}")

                if rows_to_insert:
                    if not insert_rows_resilient(client, dataset_id, temp_table_id_run, rows_to_insert, bq_schema):
                        logging.error("Failed to insert rows into temp table after retries.")
                        mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=len(rows_to_insert))
                        break

                merge_succeeded = False
                try:
                    merge_query = f'''
                        MERGE `{dataset_id}.{table_id}` T
                        USING (
                            SELECT * EXCEPT(rownum) FROM (
                                SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum FROM `{dataset_id}.{temp_table_id_run}`
                            ) WHERE rownum = 1 AND {project_filter_sql} AND Key IS NOT NULL AND TRIM(Key) <> ''
                        ) S
                        ON T.Key = S.Key
                        WHEN MATCHED THEN UPDATE SET
                            T.T = COALESCE(S.T, T.T),
                            T.Project = COALESCE(S.Project, T.Project),
                            T.IssueId = COALESCE(S.IssueId, T.IssueId),
                            T.Summary = COALESCE(S.Summary, T.Summary),
                            T.Status = COALESCE(S.Status, T.Status),
                            T.Priority = COALESCE(S.Priority, T.Priority),
                            T.Resolution = COALESCE(S.Resolution, T.Resolution),
                            T.Created = COALESCE(S.Created, T.Created),
                            T.Updated = COALESCE(S.Updated, T.Updated),
                            T.Resolved = COALESCE(S.Resolved, T.Resolved),
                            T.DueDate = COALESCE(S.DueDate, T.DueDate),
                            T.Reporter = COALESCE(S.Reporter, T.Reporter),
                            T.ReporterId = COALESCE(S.ReporterId, T.ReporterId),
                            T.Assignee = COALESCE(S.Assignee, T.Assignee),
                            T.AssigneeId = COALESCE(S.AssigneeId, T.AssigneeId),
                            T.Component = IF(S.Component IS NULL, NULL, [S.Component]),
                            T.FeatureTeam = COALESCE(S.FeatureTeam, T.FeatureTeam),
                            T.MaintenanceWindowStart = COALESCE(S.MaintenanceWindowStart, T.MaintenanceWindowStart),
                            T.MaintenanceWindowEnd = COALESCE(S.MaintenanceWindowEnd, T.MaintenanceWindowEnd),
                            T.KnowledgeManagement = COALESCE(S.KnowledgeManagement, T.KnowledgeManagement),
                            T.DirectoryInternal = COALESCE(S.DirectoryInternal, T.DirectoryInternal),
                            T.ConfluenceURL = COALESCE(S.ConfluenceURL, T.ConfluenceURL),
                            T.IncludeChildPages = COALESCE(S.IncludeChildPages, T.IncludeChildPages),
                            T.Verifier = COALESCE(S.Verifier, T.Verifier),
                            T.VerifierId = COALESCE(S.VerifierId, T.VerifierId),
                            T.Approvers = COALESCE(S.Approvers, T.Approvers),
                            T.ApproversId = COALESCE(S.ApproversId, T.ApproversId),
                            T.RemedyTicketNumber = IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]),
                            T.Links = COALESCE(S.Links, T.Links),
                            T.Description = COALESCE(S.Description, T.Description),
                            T.Labels = COALESCE(S.Labels, T.Labels),
                            T.Attachment = COALESCE(S.Attachment, T.Attachment),
                            T.{SR_REF_BQ_NAME} = COALESCE(S.{SR_REF_BQ_NAME}, T.{SR_REF_BQ_NAME}),
                            T.AssociatedTeam = COALESCE(S.AssociatedTeam, T.AssociatedTeam),
                            T.TransactionStatus = COALESCE(S.TransactionStatus, T.TransactionStatus),
                            T.Service = COALESCE(S.Service, T.Service),
                            T.Origin = COALESCE(S.Origin, T.Origin),
                            T.RootCause = COALESCE(S.RootCause, T.RootCause),
                            T.ResolutionSecurity = COALESCE(S.ResolutionSecurity, T.ResolutionSecurity),
                            T.Symptoms = COALESCE(S.Symptoms, T.Symptoms),
                            T.ATTCK = COALESCE(S.ATTCK, T.ATTCK),
                            T.StoryPoints = COALESCE(S.StoryPoints, T.StoryPoints),
                            T.TimeSpentSeconds = COALESCE(S.TimeSpentSeconds, T.TimeSpentSeconds),
                            T.TimeToFirstResponse_Elapsed_hrs = COALESCE(S.TimeToFirstResponse_Elapsed_hrs, T.TimeToFirstResponse_Elapsed_hrs),
                            T.TimeToFirstResponse_Goal_hrs = COALESCE(S.TimeToFirstResponse_Goal_hrs, T.TimeToFirstResponse_Goal_hrs),
                            T.TimeToFirstResponse_Breached = COALESCE(S.TimeToFirstResponse_Breached, T.TimeToFirstResponse_Breached),
                            T.TimeToFirstResponse_Cycles = COALESCE(S.TimeToFirstResponse_Cycles, T.TimeToFirstResponse_Cycles),
                            T.TimeToResolve_Elapsed_hrs = COALESCE(S.TimeToResolve_Elapsed_hrs, T.TimeToResolve_Elapsed_hrs),
                            T.TimeToResolve_Goal_hrs = COALESCE(S.TimeToResolve_Goal_hrs, T.TimeToResolve_Goal_hrs),
                            T.TimeToResolve_Breached = COALESCE(S.TimeToResolve_Breached, T.TimeToResolve_Breached),
                            T.TimeToResolve_Cycles = COALESCE(S.TimeToResolve_Cycles, T.TimeToResolve_Cycles),
                            T.TimeToResolution_Elapsed_hrs = COALESCE(S.TimeToResolution_Elapsed_hrs, T.TimeToResolution_Elapsed_hrs),
                            T.TimeToResolution_Goal_hrs = COALESCE(S.TimeToResolution_Goal_hrs, T.TimeToResolution_Goal_hrs),
                            T.TimeToResolution_Breached = COALESCE(S.TimeToResolution_Breached, T.TimeToResolution_Breached),
                            T.TimeToResolution_Cycles = COALESCE(S.TimeToResolution_Cycles, T.TimeToResolution_Cycles),
                            T.TimeToApproveNormalChange_Elapsed_hrs = COALESCE(S.TimeToApproveNormalChange_Elapsed_hrs, T.TimeToApproveNormalChange_Elapsed_hrs),
                            T.TimeToApproveNormalChange_Goal_hrs = COALESCE(S.TimeToApproveNormalChange_Goal_hrs, T.TimeToApproveNormalChange_Goal_hrs),
                            T.TimeToApproveNormalChange_Breached = COALESCE(S.TimeToApproveNormalChange_Breached, T.TimeToApproveNormalChange_Breached),
                            T.TimeToApproveNormalChange_Cycles = COALESCE(S.TimeToApproveNormalChange_Cycles, T.TimeToApproveNormalChange_Cycles),
                            T.ProlongCase_Elapsed_hrs = COALESCE(S.ProlongCase_Elapsed_hrs, T.ProlongCase_Elapsed_hrs),
                            T.ProlongCase_Goal_hrs = COALESCE(S.ProlongCase_Goal_hrs, T.ProlongCase_Goal_hrs),
                            T.ProlongCase_Breached = COALESCE(S.ProlongCase_Breached, T.ProlongCase_Breached),
                            T.ProlongCase_Cycles = COALESCE(S.ProlongCase_Cycles, T.ProlongCase_Cycles),
                            T.TimeToCloseAfterResolution_Elapsed_hrs = COALESCE(S.TimeToCloseAfterResolution_Elapsed_hrs, T.TimeToCloseAfterResolution_Elapsed_hrs),
                            T.TimeToCloseAfterResolution_Goal_hrs = COALESCE(S.TimeToCloseAfterResolution_Goal_hrs, T.TimeToCloseAfterResolution_Goal_hrs),
                            T.TimeToCloseAfterResolution_Breached = COALESCE(S.TimeToCloseAfterResolution_Breached, T.TimeToCloseAfterResolution_Breached),
                            T.TimeToCloseAfterResolution_Cycles = COALESCE(S.TimeToCloseAfterResolution_Cycles, T.TimeToCloseAfterResolution_Cycles),
                            T.ITHD_TimeToFirstResponse_Elapsed_hrs = COALESCE(S.ITHD_TimeToFirstResponse_Elapsed_hrs, T.ITHD_TimeToFirstResponse_Elapsed_hrs),
                            T.ITHD_TimeToFirstResponse_Goal_hrs = COALESCE(S.ITHD_TimeToFirstResponse_Goal_hrs, T.ITHD_TimeToFirstResponse_Goal_hrs),
                            T.ITHD_TimeToFirstResponse_Breached = COALESCE(S.ITHD_TimeToFirstResponse_Breached, T.ITHD_TimeToFirstResponse_Breached),
                            T.ITHD_TimeToFirstResponse_Cycles = COALESCE(S.ITHD_TimeToFirstResponse_Cycles, T.ITHD_TimeToFirstResponse_Cycles),
                            T.ITHD_TimeToResolution_Elapsed_hrs = COALESCE(S.ITHD_TimeToResolution_Elapsed_hrs, T.ITHD_TimeToResolution_Elapsed_hrs),
                            T.ITHD_TimeToResolution_Goal_hrs = COALESCE(S.ITHD_TimeToResolution_Goal_hrs, T.ITHD_TimeToResolution_Goal_hrs),
                            T.ITHD_TimeToResolution_Breached = COALESCE(S.ITHD_TimeToResolution_Breached, T.ITHD_TimeToResolution_Breached),
                            T.ITHD_TimeToResolution_Cycles = COALESCE(S.ITHD_TimeToResolution_Cycles, T.ITHD_TimeToResolution_Cycles),
                            T.ITHD_ISMSIncidentResponse_Elapsed_hrs = COALESCE(S.ITHD_ISMSIncidentResponse_Elapsed_hrs, T.ITHD_ISMSIncidentResponse_Elapsed_hrs),
                            T.ITHD_ISMSIncidentResponse_Goal_hrs = COALESCE(S.ITHD_ISMSIncidentResponse_Goal_hrs, T.ITHD_ISMSIncidentResponse_Goal_hrs),
                            T.ITHD_ISMSIncidentResponse_Breached = COALESCE(S.ITHD_ISMSIncidentResponse_Breached, T.ITHD_ISMSIncidentResponse_Breached),
                            T.ITHD_ISMSIncidentResponse_Cycles = COALESCE(S.ITHD_ISMSIncidentResponse_Cycles, T.ITHD_ISMSIncidentResponse_Cycles),
                            T.ITHD_ISMSIncidentResolution_Elapsed_hrs = COALESCE(S.ITHD_ISMSIncidentResolution_Elapsed_hrs, T.ITHD_ISMSIncidentResolution_Elapsed_hrs),
                            T.ITHD_ISMSIncidentResolution_Goal_hrs = COALESCE(S.ITHD_ISMSIncidentResolution_Goal_hrs, T.ITHD_ISMSIncidentResolution_Goal_hrs),
                            T.ITHD_ISMSIncidentResolution_Breached = COALESCE(S.ITHD_ISMSIncidentResolution_Breached, T.ITHD_ISMSIncidentResolution_Breached),
                            T.ITHD_ISMSIncidentResolution_Cycles = COALESCE(S.ITHD_ISMSIncidentResolution_Cycles, T.ITHD_ISMSIncidentResolution_Cycles),
                            T.ITHD_Resolution = COALESCE(S.ITHD_Resolution, T.ITHD_Resolution),
                            T.AppSupEscalation = COALESCE(S.AppSupEscalation, T.AppSupEscalation),
                            T.SyncTime = COALESCE(S.SyncTime, T.SyncTime),
                            T.IsDeleted = FALSE,
                            T.DeletedAt = NULL
                        WHEN NOT MATCHED THEN INSERT (T, Project, Key, IssueId, Summary, Status, Priority, Resolution, Created, Updated, Resolved, DueDate, Reporter, ReporterId, Assignee, AssigneeId, Component, FeatureTeam, MaintenanceWindowStart, MaintenanceWindowEnd, KnowledgeManagement, DirectoryInternal, ConfluenceURL, IncludeChildPages, Verifier, VerifierId, Approvers, ApproversId, RemedyTicketNumber, Links, Description, Labels, Attachment, {SR_REF_BQ_NAME}, AssociatedTeam, TransactionStatus, Service, Origin, RootCause, ResolutionSecurity, Symptoms, ATTCK, StoryPoints, TimeSpentSeconds, TimeToFirstResponse_Elapsed_hrs, TimeToFirstResponse_Goal_hrs, TimeToFirstResponse_Breached, TimeToFirstResponse_Cycles, TimeToResolve_Elapsed_hrs, TimeToResolve_Goal_hrs, TimeToResolve_Breached, TimeToResolve_Cycles, TimeToResolution_Elapsed_hrs, TimeToResolution_Goal_hrs, TimeToResolution_Breached, TimeToResolution_Cycles, TimeToApproveNormalChange_Elapsed_hrs, TimeToApproveNormalChange_Goal_hrs, TimeToApproveNormalChange_Breached, TimeToApproveNormalChange_Cycles, ProlongCase_Elapsed_hrs, ProlongCase_Goal_hrs, ProlongCase_Breached, ProlongCase_Cycles, TimeToCloseAfterResolution_Elapsed_hrs, TimeToCloseAfterResolution_Goal_hrs, TimeToCloseAfterResolution_Breached, TimeToCloseAfterResolution_Cycles, ITHD_TimeToFirstResponse_Elapsed_hrs, ITHD_TimeToFirstResponse_Goal_hrs, ITHD_TimeToFirstResponse_Breached, ITHD_TimeToFirstResponse_Cycles, ITHD_TimeToResolution_Elapsed_hrs, ITHD_TimeToResolution_Goal_hrs, ITHD_TimeToResolution_Breached, ITHD_TimeToResolution_Cycles, ITHD_ISMSIncidentResponse_Elapsed_hrs, ITHD_ISMSIncidentResponse_Goal_hrs, ITHD_ISMSIncidentResponse_Breached, ITHD_ISMSIncidentResponse_Cycles, ITHD_ISMSIncidentResolution_Elapsed_hrs, ITHD_ISMSIncidentResolution_Goal_hrs, ITHD_ISMSIncidentResolution_Breached, ITHD_ISMSIncidentResolution_Cycles, ITHD_Resolution, AppSupEscalation, SyncTime, IsDeleted, DeletedAt)
                        VALUES (S.T, S.Project, S.Key, S.IssueId, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.DueDate, S.Reporter, S.ReporterId, S.Assignee, S.AssigneeId, IF(S.Component IS NULL, NULL, [S.Component]), S.FeatureTeam, S.MaintenanceWindowStart, S.MaintenanceWindowEnd, S.KnowledgeManagement, S.DirectoryInternal, S.ConfluenceURL, S.IncludeChildPages, S.Verifier, S.VerifierId, S.Approvers, S.ApproversId, IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]), S.Links, S.Description, S.Labels, S.Attachment, S.{SR_REF_BQ_NAME}, S.AssociatedTeam, S.TransactionStatus, S.Service, S.Origin, S.RootCause, S.ResolutionSecurity, S.Symptoms, S.ATTCK, S.StoryPoints, S.TimeSpentSeconds, S.TimeToFirstResponse_Elapsed_hrs, S.TimeToFirstResponse_Goal_hrs, S.TimeToFirstResponse_Breached, S.TimeToFirstResponse_Cycles, S.TimeToResolve_Elapsed_hrs, S.TimeToResolve_Goal_hrs, S.TimeToResolve_Breached, S.TimeToResolve_Cycles, S.TimeToResolution_Elapsed_hrs, S.TimeToResolution_Goal_hrs, S.TimeToResolution_Breached, S.TimeToResolution_Cycles, S.TimeToApproveNormalChange_Elapsed_hrs, S.TimeToApproveNormalChange_Goal_hrs, S.TimeToApproveNormalChange_Breached, S.TimeToApproveNormalChange_Cycles, S.ProlongCase_Elapsed_hrs, S.ProlongCase_Goal_hrs, S.ProlongCase_Breached, S.ProlongCase_Cycles, S.TimeToCloseAfterResolution_Elapsed_hrs, S.TimeToCloseAfterResolution_Goal_hrs, S.TimeToCloseAfterResolution_Breached, S.TimeToCloseAfterResolution_Cycles, S.ITHD_TimeToFirstResponse_Elapsed_hrs, S.ITHD_TimeToFirstResponse_Goal_hrs, S.ITHD_TimeToFirstResponse_Breached, S.ITHD_TimeToFirstResponse_Cycles, S.ITHD_TimeToResolution_Elapsed_hrs, S.ITHD_TimeToResolution_Goal_hrs, S.ITHD_TimeToResolution_Breached, S.ITHD_TimeToResolution_Cycles, S.ITHD_ISMSIncidentResponse_Elapsed_hrs, S.ITHD_ISMSIncidentResponse_Goal_hrs, S.ITHD_ISMSIncidentResponse_Breached, S.ITHD_ISMSIncidentResponse_Cycles, S.ITHD_ISMSIncidentResolution_Elapsed_hrs, S.ITHD_ISMSIncidentResolution_Goal_hrs, S.ITHD_ISMSIncidentResolution_Breached, S.ITHD_ISMSIncidentResolution_Cycles, S.ITHD_Resolution, S.AppSupEscalation, S.SyncTime, FALSE, NULL)
                    '''
                    execute_bq_query_with_retry(client, merge_query, max_retries=5, initial_delay=10.0)
                    logging.info(f"Merged temp table into '{dataset_id}.{table_id}'.")
                    merge_succeeded = True
                except Exception as e:
                    logging.error(f"Error merging temp table for {proj}: {e}")
                    mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'failed', row_count=0)
                    break

                if not merge_succeeded:
                    break

                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                total_rows_merged += len(rows_to_insert)
                mark_progress(client, dataset_id, progress_table_id, proj, ws, we, 'complete', row_count=len(rows_to_insert))
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="INFO",
                    message="Window complete",
                    status="SUCCESS",
                    rows_merged=len(rows_to_insert),
                    duration_seconds=duration_seconds,
                    window_start=ws.strftime('%Y-%m-%d %H:%M:%S'),
                    window_end=we.strftime('%Y-%m-%d %H:%M:%S'),
                )
                # Move to next window for this project

            if budget_reached:
                break

            # Nightly catch-up: fill active Jira keys missing in BQ.
            if MISSING_KEY_CATCHUP_PER_PROJECT > 0 and not budget_reached:
                try:
                    catchup_keys, catchup_had_error = search_issue_keys(proj_clause, f'catchup_keyset:{proj}')
                    if catchup_had_error:
                        logging.warning(f"[{proj}] Catch-up skipped due to Jira key search errors")
                        run_had_errors = True
                        continue
                    project_current_keys = {k for k in catchup_keys if k}
                    known_keys = get_known_project_keys(client, dataset_id, table_id, proj)
                    
                    # Find missing keys
                    missing_keys = sorted([k for k in project_current_keys if k not in known_keys])

                    # Limit total per run
                    to_fetch = missing_keys[:MISSING_KEY_CATCHUP_PER_PROJECT]
                    
                    if to_fetch:
                        logging.info(
                            f"[{proj}] Catch-up: {len(missing_keys)} missing keys; "
                            f"fetching {len(to_fetch)} this run"
                        )

                        # Use batched fetch and insert to minimize memory usage
                        catchup_rows_count = fetch_and_insert_ticket_rows_batched(
                            to_fetch, f'catchup:{proj}', dataset_id, temp_table_id_run, bq_schema, stop_checker=time_budget_reached
                        )

                        if catchup_rows_count > 0:
                            merge_query = f'''
                                MERGE `{dataset_id}.{table_id}` T
                                USING (
                                    SELECT * EXCEPT(rownum) FROM (
                                        SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum
                                        FROM `{dataset_id}.{temp_table_id_run}`
                                    ) WHERE rownum = 1 AND {project_filter_sql} AND Key IS NOT NULL AND TRIM(Key) <> ''
                                ) S
                                ON T.Key = S.Key
                                WHEN MATCHED THEN UPDATE SET
                                    T.T = COALESCE(S.T, T.T),
                                    T.Project = COALESCE(S.Project, T.Project),
                                    T.IssueId = COALESCE(S.IssueId, T.IssueId),
                                    T.Summary = COALESCE(S.Summary, T.Summary),
                                    T.Status = COALESCE(S.Status, T.Status),
                                    T.Priority = COALESCE(S.Priority, T.Priority),
                                    T.Resolution = COALESCE(S.Resolution, T.Resolution),
                                    T.Created = COALESCE(S.Created, T.Created),
                                    T.Updated = COALESCE(S.Updated, T.Updated),
                                    T.Resolved = COALESCE(S.Resolved, T.Resolved),
                                    T.DueDate = COALESCE(S.DueDate, T.DueDate),
                                    T.Reporter = COALESCE(S.Reporter, T.Reporter),
                                    T.ReporterId = COALESCE(S.ReporterId, T.ReporterId),
                                    T.Assignee = COALESCE(S.Assignee, T.Assignee),
                                    T.AssigneeId = COALESCE(S.AssigneeId, T.AssigneeId),
                                    T.Component = IF(S.Component IS NULL, NULL, [S.Component]),
                                    T.FeatureTeam = COALESCE(S.FeatureTeam, T.FeatureTeam),
                                    T.MaintenanceWindowStart = COALESCE(S.MaintenanceWindowStart, T.MaintenanceWindowStart),
                                    T.MaintenanceWindowEnd = COALESCE(S.MaintenanceWindowEnd, T.MaintenanceWindowEnd),
                                    T.KnowledgeManagement = COALESCE(S.KnowledgeManagement, T.KnowledgeManagement),
                                    T.DirectoryInternal = COALESCE(S.DirectoryInternal, T.DirectoryInternal),
                                    T.ConfluenceURL = COALESCE(S.ConfluenceURL, T.ConfluenceURL),
                                    T.IncludeChildPages = COALESCE(S.IncludeChildPages, T.IncludeChildPages),
                                    T.Verifier = COALESCE(S.Verifier, T.Verifier),
                                    T.VerifierId = COALESCE(S.VerifierId, T.VerifierId),
                                    T.Approvers = COALESCE(S.Approvers, T.Approvers),
                                    T.ApproversId = COALESCE(S.ApproversId, T.ApproversId),
                                    T.RemedyTicketNumber = IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]),
                                    T.Links = COALESCE(S.Links, T.Links),
                                    T.Description = COALESCE(S.Description, T.Description),
                                    T.Labels = COALESCE(S.Labels, T.Labels),
                                    T.Attachment = COALESCE(S.Attachment, T.Attachment),
                                    T.{SR_REF_BQ_NAME} = COALESCE(S.{SR_REF_BQ_NAME}, T.{SR_REF_BQ_NAME}),
                                    T.AssociatedTeam = COALESCE(S.AssociatedTeam, T.AssociatedTeam),
                                    T.TransactionStatus = COALESCE(S.TransactionStatus, T.TransactionStatus),
                                    T.Service = COALESCE(S.Service, T.Service),
                                    T.Origin = COALESCE(S.Origin, T.Origin),
                                    T.RootCause = COALESCE(S.RootCause, T.RootCause),
                                    T.ResolutionSecurity = COALESCE(S.ResolutionSecurity, T.ResolutionSecurity),
                                    T.Symptoms = COALESCE(S.Symptoms, T.Symptoms),
                                    T.ATTCK = COALESCE(S.ATTCK, T.ATTCK),
                                    T.StoryPoints = COALESCE(S.StoryPoints, T.StoryPoints),
                                    T.TimeSpentSeconds = COALESCE(S.TimeSpentSeconds, T.TimeSpentSeconds),
                                    T.TimeToFirstResponse_Elapsed_hrs = COALESCE(S.TimeToFirstResponse_Elapsed_hrs, T.TimeToFirstResponse_Elapsed_hrs),
                                    T.TimeToFirstResponse_Goal_hrs = COALESCE(S.TimeToFirstResponse_Goal_hrs, T.TimeToFirstResponse_Goal_hrs),
                                    T.TimeToFirstResponse_Breached = COALESCE(S.TimeToFirstResponse_Breached, T.TimeToFirstResponse_Breached),
                                    T.TimeToFirstResponse_Cycles = COALESCE(S.TimeToFirstResponse_Cycles, T.TimeToFirstResponse_Cycles),
                                    T.TimeToResolve_Elapsed_hrs = COALESCE(S.TimeToResolve_Elapsed_hrs, T.TimeToResolve_Elapsed_hrs),
                                    T.TimeToResolve_Goal_hrs = COALESCE(S.TimeToResolve_Goal_hrs, T.TimeToResolve_Goal_hrs),
                                    T.TimeToResolve_Breached = COALESCE(S.TimeToResolve_Breached, T.TimeToResolve_Breached),
                                    T.TimeToResolve_Cycles = COALESCE(S.TimeToResolve_Cycles, T.TimeToResolve_Cycles),
                                    T.TimeToResolution_Elapsed_hrs = COALESCE(S.TimeToResolution_Elapsed_hrs, T.TimeToResolution_Elapsed_hrs),
                                    T.TimeToResolution_Goal_hrs = COALESCE(S.TimeToResolution_Goal_hrs, T.TimeToResolution_Goal_hrs),
                                    T.TimeToResolution_Breached = COALESCE(S.TimeToResolution_Breached, T.TimeToResolution_Breached),
                                    T.TimeToResolution_Cycles = COALESCE(S.TimeToResolution_Cycles, T.TimeToResolution_Cycles),
                                    T.TimeToApproveNormalChange_Elapsed_hrs = COALESCE(S.TimeToApproveNormalChange_Elapsed_hrs, T.TimeToApproveNormalChange_Elapsed_hrs),
                                    T.TimeToApproveNormalChange_Goal_hrs = COALESCE(S.TimeToApproveNormalChange_Goal_hrs, T.TimeToApproveNormalChange_Goal_hrs),
                                    T.TimeToApproveNormalChange_Breached = COALESCE(S.TimeToApproveNormalChange_Breached, T.TimeToApproveNormalChange_Breached),
                                    T.TimeToApproveNormalChange_Cycles = COALESCE(S.TimeToApproveNormalChange_Cycles, T.TimeToApproveNormalChange_Cycles),
                                    T.ProlongCase_Elapsed_hrs = COALESCE(S.ProlongCase_Elapsed_hrs, T.ProlongCase_Elapsed_hrs),
                                    T.ProlongCase_Goal_hrs = COALESCE(S.ProlongCase_Goal_hrs, T.ProlongCase_Goal_hrs),
                                    T.ProlongCase_Breached = COALESCE(S.ProlongCase_Breached, T.ProlongCase_Breached),
                                    T.ProlongCase_Cycles = COALESCE(S.ProlongCase_Cycles, T.ProlongCase_Cycles),
                                    T.TimeToCloseAfterResolution_Elapsed_hrs = COALESCE(S.TimeToCloseAfterResolution_Elapsed_hrs, T.TimeToCloseAfterResolution_Elapsed_hrs),
                                    T.TimeToCloseAfterResolution_Goal_hrs = COALESCE(S.TimeToCloseAfterResolution_Goal_hrs, T.TimeToCloseAfterResolution_Goal_hrs),
                                    T.TimeToCloseAfterResolution_Breached = COALESCE(S.TimeToCloseAfterResolution_Breached, T.TimeToCloseAfterResolution_Breached),
                                    T.TimeToCloseAfterResolution_Cycles = COALESCE(S.TimeToCloseAfterResolution_Cycles, T.TimeToCloseAfterResolution_Cycles),
                                    T.ITHD_TimeToFirstResponse_Elapsed_hrs = COALESCE(S.ITHD_TimeToFirstResponse_Elapsed_hrs, T.ITHD_TimeToFirstResponse_Elapsed_hrs),
                                    T.ITHD_TimeToFirstResponse_Goal_hrs = COALESCE(S.ITHD_TimeToFirstResponse_Goal_hrs, T.ITHD_TimeToFirstResponse_Goal_hrs),
                                    T.ITHD_TimeToFirstResponse_Breached = COALESCE(S.ITHD_TimeToFirstResponse_Breached, T.ITHD_TimeToFirstResponse_Breached),
                                    T.ITHD_TimeToFirstResponse_Cycles = COALESCE(S.ITHD_TimeToFirstResponse_Cycles, T.ITHD_TimeToFirstResponse_Cycles),
                                    T.ITHD_TimeToResolution_Elapsed_hrs = COALESCE(S.ITHD_TimeToResolution_Elapsed_hrs, T.ITHD_TimeToResolution_Elapsed_hrs),
                                    T.ITHD_TimeToResolution_Goal_hrs = COALESCE(S.ITHD_TimeToResolution_Goal_hrs, T.ITHD_TimeToResolution_Goal_hrs),
                                    T.ITHD_TimeToResolution_Breached = COALESCE(S.ITHD_TimeToResolution_Breached, T.ITHD_TimeToResolution_Breached),
                                    T.ITHD_TimeToResolution_Cycles = COALESCE(S.ITHD_TimeToResolution_Cycles, T.ITHD_TimeToResolution_Cycles),
                                    T.ITHD_ISMSIncidentResponse_Elapsed_hrs = COALESCE(S.ITHD_ISMSIncidentResponse_Elapsed_hrs, T.ITHD_ISMSIncidentResponse_Elapsed_hrs),
                                    T.ITHD_ISMSIncidentResponse_Goal_hrs = COALESCE(S.ITHD_ISMSIncidentResponse_Goal_hrs, T.ITHD_ISMSIncidentResponse_Goal_hrs),
                                    T.ITHD_ISMSIncidentResponse_Breached = COALESCE(S.ITHD_ISMSIncidentResponse_Breached, T.ITHD_ISMSIncidentResponse_Breached),
                                    T.ITHD_ISMSIncidentResponse_Cycles = COALESCE(S.ITHD_ISMSIncidentResponse_Cycles, T.ITHD_ISMSIncidentResponse_Cycles),
                                    T.ITHD_ISMSIncidentResolution_Elapsed_hrs = COALESCE(S.ITHD_ISMSIncidentResolution_Elapsed_hrs, T.ITHD_ISMSIncidentResolution_Elapsed_hrs),
                                    T.ITHD_ISMSIncidentResolution_Goal_hrs = COALESCE(S.ITHD_ISMSIncidentResolution_Goal_hrs, T.ITHD_ISMSIncidentResolution_Goal_hrs),
                                    T.ITHD_ISMSIncidentResolution_Breached = COALESCE(S.ITHD_ISMSIncidentResolution_Breached, T.ITHD_ISMSIncidentResolution_Breached),
                                    T.ITHD_ISMSIncidentResolution_Cycles = COALESCE(S.ITHD_ISMSIncidentResolution_Cycles, T.ITHD_ISMSIncidentResolution_Cycles),
                                    T.ITHD_Resolution = COALESCE(S.ITHD_Resolution, T.ITHD_Resolution),
                                    T.AppSupEscalation = COALESCE(S.AppSupEscalation, T.AppSupEscalation),
                                    T.SyncTime = COALESCE(S.SyncTime, T.SyncTime),
                                    T.IsDeleted = FALSE,
                                    T.DeletedAt = NULL
                                WHEN NOT MATCHED THEN INSERT (T, Project, Key, IssueId, Summary, Status, Priority, Resolution, Created, Updated, Resolved, DueDate, Reporter, ReporterId, Assignee, AssigneeId, Component, FeatureTeam, MaintenanceWindowStart, MaintenanceWindowEnd, KnowledgeManagement, DirectoryInternal, ConfluenceURL, IncludeChildPages, Verifier, VerifierId, Approvers, ApproversId, RemedyTicketNumber, Links, Description, Labels, Attachment, {SR_REF_BQ_NAME}, AssociatedTeam, TransactionStatus, Service, Origin, RootCause, ResolutionSecurity, Symptoms, ATTCK, StoryPoints, TimeSpentSeconds, TimeToFirstResponse_Elapsed_hrs, TimeToFirstResponse_Goal_hrs, TimeToFirstResponse_Breached, TimeToFirstResponse_Cycles, TimeToResolve_Elapsed_hrs, TimeToResolve_Goal_hrs, TimeToResolve_Breached, TimeToResolve_Cycles, TimeToResolution_Elapsed_hrs, TimeToResolution_Goal_hrs, TimeToResolution_Breached, TimeToResolution_Cycles, TimeToApproveNormalChange_Elapsed_hrs, TimeToApproveNormalChange_Goal_hrs, TimeToApproveNormalChange_Breached, TimeToApproveNormalChange_Cycles, ProlongCase_Elapsed_hrs, ProlongCase_Goal_hrs, ProlongCase_Breached, ProlongCase_Cycles, TimeToCloseAfterResolution_Elapsed_hrs, TimeToCloseAfterResolution_Goal_hrs, TimeToCloseAfterResolution_Breached, TimeToCloseAfterResolution_Cycles, ITHD_TimeToFirstResponse_Elapsed_hrs, ITHD_TimeToFirstResponse_Goal_hrs, ITHD_TimeToFirstResponse_Breached, ITHD_TimeToFirstResponse_Cycles, ITHD_TimeToResolution_Elapsed_hrs, ITHD_TimeToResolution_Goal_hrs, ITHD_TimeToResolution_Breached, ITHD_TimeToResolution_Cycles, ITHD_ISMSIncidentResponse_Elapsed_hrs, ITHD_ISMSIncidentResponse_Goal_hrs, ITHD_ISMSIncidentResponse_Breached, ITHD_ISMSIncidentResponse_Cycles, ITHD_ISMSIncidentResolution_Elapsed_hrs, ITHD_ISMSIncidentResolution_Goal_hrs, ITHD_ISMSIncidentResolution_Breached, ITHD_ISMSIncidentResolution_Cycles, ITHD_Resolution, AppSupEscalation, SyncTime, IsDeleted, DeletedAt)
                                VALUES (S.T, S.Project, S.Key, S.IssueId, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.DueDate, S.Reporter, S.ReporterId, S.Assignee, S.AssigneeId, IF(S.Component IS NULL, NULL, [S.Component]), S.FeatureTeam, S.MaintenanceWindowStart, S.MaintenanceWindowEnd, S.KnowledgeManagement, S.DirectoryInternal, S.ConfluenceURL, S.IncludeChildPages, S.Verifier, S.VerifierId, S.Approvers, S.ApproversId, IF(S.RemedyTicketNumber IS NULL, NULL, [S.RemedyTicketNumber]), S.Links, S.Description, S.Labels, S.Attachment, S.{SR_REF_BQ_NAME}, S.AssociatedTeam, S.TransactionStatus, S.Service, S.Origin, S.RootCause, S.ResolutionSecurity, S.Symptoms, S.ATTCK, S.StoryPoints, S.TimeSpentSeconds, S.TimeToFirstResponse_Elapsed_hrs, S.TimeToFirstResponse_Goal_hrs, S.TimeToFirstResponse_Breached, S.TimeToFirstResponse_Cycles, S.TimeToResolve_Elapsed_hrs, S.TimeToResolve_Goal_hrs, S.TimeToResolve_Breached, S.TimeToResolve_Cycles, S.TimeToResolution_Elapsed_hrs, S.TimeToResolution_Goal_hrs, S.TimeToResolution_Breached, S.TimeToResolution_Cycles, S.TimeToApproveNormalChange_Elapsed_hrs, S.TimeToApproveNormalChange_Goal_hrs, S.TimeToApproveNormalChange_Breached, S.TimeToApproveNormalChange_Cycles, S.ProlongCase_Elapsed_hrs, S.ProlongCase_Goal_hrs, S.ProlongCase_Breached, S.ProlongCase_Cycles, S.TimeToCloseAfterResolution_Elapsed_hrs, S.TimeToCloseAfterResolution_Goal_hrs, S.TimeToCloseAfterResolution_Breached, S.TimeToCloseAfterResolution_Cycles, S.ITHD_TimeToFirstResponse_Elapsed_hrs, S.ITHD_TimeToFirstResponse_Goal_hrs, S.ITHD_TimeToFirstResponse_Breached, S.ITHD_TimeToFirstResponse_Cycles, S.ITHD_TimeToResolution_Elapsed_hrs, S.ITHD_TimeToResolution_Goal_hrs, S.ITHD_TimeToResolution_Breached, S.ITHD_TimeToResolution_Cycles, S.ITHD_ISMSIncidentResponse_Elapsed_hrs, S.ITHD_ISMSIncidentResponse_Goal_hrs, S.ITHD_ISMSIncidentResponse_Breached, S.ITHD_ISMSIncidentResponse_Cycles, S.ITHD_ISMSIncidentResolution_Elapsed_hrs, S.ITHD_ISMSIncidentResolution_Goal_hrs, S.ITHD_ISMSIncidentResolution_Breached, S.ITHD_ISMSIncidentResolution_Cycles, S.ITHD_Resolution, S.AppSupEscalation, S.SyncTime, FALSE, NULL)
                            '''
                            execute_bq_query_with_retry(client, merge_query, max_retries=5, initial_delay=10.0)
                            total_rows_merged += catchup_rows_count
                            logging.info(f"[{proj}] Catch-up merged {catchup_rows_count} missing key rows")
                except Exception as catchup_exc:
                    logging.warning(f"[{proj}] Missing-key catch-up skipped due to error: {catchup_exc}")
                    run_had_errors = True

            if budget_reached:
                break

        if budget_reached:
            final_status = "SUCCESS"
            final_level = "WARNING"
            final_message = "Run budget reached; partial progress saved"
            return

        if not ENABLE_SOFT_DELETE_RECONCILIATION:
            logging.warning("Soft-delete reconciliation disabled; skipping nightly delete-marking")
            if run_had_errors:
                final_status = "ERROR"
                final_level = "ERROR"
                final_message = "Pipeline finished with one or more errors"
            else:
                final_status = "SUCCESS"
                final_level = "INFO"
                final_message = "Pipeline finished"
            return

        # Reconciliation step: mark rows as soft-deleted if key no longer exists in Jira.
        active_keys = set()
        failed_projects = []
        for proj in projects:
            proj_clause = f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            current_keys, had_error = search_issue_keys(proj_clause, f'full_keyset:{proj}')
            if had_error:
                failed_projects.append(proj)
                continue
            for key in current_keys:
                active_keys.add(key)

        if failed_projects:
            failed_projects_str = ', '.join(failed_projects)
            logging.error(f"Soft-delete reconciliation skipped due to Jira key fetch errors for projects: {failed_projects_str}")
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="WARNING",
                message=f"Soft-delete reconciliation skipped due to Jira key fetch errors for: {failed_projects_str}",
                status="SUCCESS",
            )
            run_had_errors = True
            final_status = "ERROR"
            final_level = "ERROR"
            final_message = "Pipeline finished with one or more errors"
            return

        keys_table_id = f"JiraTickets_active_keys_{run_id.replace('-', '_')[:8]}"
        keys_schema = [bigquery.SchemaField("Key", "STRING", mode="REQUIRED")]
        if not create_or_replace_temp_table(client, dataset_id, keys_table_id, keys_schema):
            raise Exception("Failed to create active key snapshot table for soft-delete reconciliation")
        if not wait_for_table(client, dataset_id, keys_table_id, retries=30, delay=2):
            raise Exception("Active key snapshot table was not available for reconciliation")

        keys_rows = [{"Key": k} for k in active_keys]
        if keys_rows:
            if not insert_rows_resilient(client, dataset_id, keys_table_id, keys_rows, keys_schema):
                raise Exception("Failed to populate active key snapshot table")

        scoped_projects = _to_sql_string_list(projects)
        mark_deleted_query = f'''
            UPDATE `{dataset_id}.{table_id}` T
            SET IsDeleted = TRUE,
                DeletedAt = CURRENT_TIMESTAMP()
            WHERE T.Project IN ({scoped_projects})
                            AND T.Key IS NOT NULL
                            AND TRIM(T.Key) <> ''
              AND (T.IsDeleted IS NULL OR T.IsDeleted = FALSE)
              AND NOT EXISTS (
                SELECT 1
                FROM `{dataset_id}.{keys_table_id}` S
                WHERE S.Key = T.Key
              )
        '''
        client.query(mark_deleted_query).result()

        clear_deleted_query = f'''
            UPDATE `{dataset_id}.{table_id}` T
            SET IsDeleted = FALSE,
                DeletedAt = NULL
            WHERE T.Project IN ({scoped_projects})
                            AND T.Key IS NOT NULL
                            AND TRIM(T.Key) <> ''
              AND EXISTS (
                SELECT 1
                FROM `{dataset_id}.{keys_table_id}` S
                WHERE S.Key = T.Key
              )
              AND (T.IsDeleted IS TRUE OR T.DeletedAt IS NOT NULL)
        '''
        client.query(clear_deleted_query).result()

        delete_temp_table(client, dataset_id, keys_table_id)

        if run_had_errors:
            final_status = "ERROR"
            final_level = "ERROR"
            final_message = "Pipeline finished with one or more errors"
        else:
            final_status = "SUCCESS"
            final_level = "INFO"
            final_message = "Pipeline finished"
    except Exception as e:
        final_status = "ERROR"
        final_level = "ERROR"
        final_message = f"Exception: {e}"
        final_error_code = getattr(e, "code", None)
        raise
    finally:
        try:
            if client and run_started:
                run_ended = datetime.now(timezone.utc)
                duration_seconds = (run_ended - run_started).total_seconds()
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level=final_level,
                    message=final_message,
                    status=final_status,
                    rows_merged=total_rows_merged,
                    error_code=final_error_code,
                    duration_seconds=duration_seconds,
                )
        except Exception as log_err:
            logging.warning(f"Failed to write final pipeline status for {run_id}: {log_err}")

        try:
            if client and temp_table_id_run:
                delete_temp_table(client, dataset_id, temp_table_id_run)
        except Exception as cleanup_err:
            logging.warning(f"Failed to cleanup temp table {temp_table_id_run}: {cleanup_err}")

@functions_framework.http
def main(request):
    # Cleanup stale RUNNING entries older than RUNNING_STALE_MINUTES
    try:
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        cleanup_query = f'''
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = 'GCP - JiraTicketsNightly'
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {RUNNING_STALE_MINUTES} MINUTE)
        '''
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    try:
        fetch_and_sync_jira_tickets_nightly()
        return {"status": "success", "message": "Jira tickets nightly sync completed"}, 200
    except Exception as e:
        logging.error(f"Cloud Function failed: {e}")
        return {"status": "error", "message": str(e)}, 500
