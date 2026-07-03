"""
Cloud Function to process BigQuery HDWL emails from Gmail.
Receives Pub/Sub messages, downloads attachments, processes CSV files,
loads to BigQuery, manages labels, and logs pipeline runs.
"""

import base64
import json
import csv
import io
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import functions_framework
from google.api_core.exceptions import NotFound
from google.oauth2.credentials import Credentials
from google.cloud import secretmanager, pubsub_v1, bigquery
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"
PIPELINE_RUNS_TABLE = "PipelineRuns"
SCRIPT_NAME = "pubsub - HDWL"
ERROR_NOTIFICATION_EMAIL = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com"

# Global tracking for pipeline run timing
_script_start_time = None
_current_run_id = None
_bq_client = None


def get_bq_client() -> bigquery.Client:
    """Reuse one BigQuery client per instance to reduce connection churn."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client

# CSV type configurations
CSV_CONFIGURATIONS = [
    {
        "name": "HelpDeskAllNOC",
        "filename_prefix": "helpdesk",
        "staging_dataset": "Staging",
        "staging_table": "HelpDeskAllNOC",
        "target_dataset": "GSO",
        "target_table": "HelpDeskAllNOC",
        "primary_key": "Incident_Number",
        "all_columns": [
            "Incident_Number", "Status", "CaseType", "Assigned_Group", "Categorization_Tier_1",
            "Categorization_Tier_2", "Categorization_Tier_3", "GCSC_1st_Customer_Update",
            "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update", "Initial_Response_Time",
            "Second_Response_Time", "Third_Response_Time", "Prod_ID", "Fault_Cause",
            "Closed_Date", "Submit_Date", "Assignee", "Closed_By", "Submitter", "TrueMTTR_mins",
            "Cust_ID", "Carrier", "Customer_Name", "SRno", "LastResolvedDate", "ReportedDate",
            "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy",
            "Product_Family", "ProductDescription", "GSMP_Circuit_ID"
        ],
        "field_map": {
            "IncidentNumber": "Incident_Number", "casetype": "CaseType", "Assigned Group": "Assigned_Group",
            "Categorization Tier 1": "Categorization_Tier_1", "Categorization Tier 2": "Categorization_Tier_2",
            "Categorization Tier 3": "Categorization_Tier_3", "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
            "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update", "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
            "Initial Response Time": "Initial_Response_Time", "Second Response Time": "Second_Response_Time",
            "Third Response Time": "Third_Response_Time", "Prod ID": "Prod_ID", "FaultCause": "Fault_Cause",
            "Closed Date": "Closed_Date", "Submit Date": "Submit_Date", "ClosedBy": "Closed_By",
            "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRno": "SRno", "ReportedBy": "ReportedBy",
            "Product Family": "Product_Family", "ProductDescription": "ProductDescription",
            "GSMP Circuit ID": "GSMP_Circuit_ID"
        },
        "timestamp_fields": [
            "GCSC_1st_Customer_Update", "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update",
            "Closed_Date", "Submit_Date", "LastResolvedDate", "ReportedDate", "RespondedDate",
            "LastModifiedDate"
        ],
        "integer_fields": ["Initial_Response_Time", "Second_Response_Time", "Third_Response_Time", "TrueMTTR_mins"]
    },
    {
        "name": "WorkLog",
        "filename_prefix": "worklog",
        "staging_dataset": "Staging",
        "staging_table": "WorkLogAllNOC",
        "target_dataset": "GSO",
        "target_table": "WorkLogAllNOC",
        "primary_key": "WorkLog_ID",
        "all_columns": [
            "Incident_Number", "WorkLog_Type", "WorkLog_ID", "WorkLog_Submit_Date",
            "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By", "ExtractedDescription"
        ],
        "field_map": {
            "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
            "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
            "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
            "LastModifiedBy": "Last_Modified_By", "ExtractedDescription": "ExtractedDescription"
        },
        "timestamp_fields": ["WorkLog_Submit_Date", "Last_Modified_Date"],
        "integer_fields": []
    }
]


def load_oauth_credentials():
    """Load OAuth credentials from Secret Manager"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-token/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        token_json = response.payload.data.decode("UTF-8")
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data)
        return creds
    except Exception as e:
        logger.error(f"Failed to load OAuth credentials: {e}")
        raise


def get_gmail_service():
    """Get Gmail API service"""
    creds = load_oauth_credentials()
    return build('gmail', 'v1', credentials=creds)


def get_message_attachment(service, message_id: str, attachment_filename: str) -> Optional[bytes]:
    """Get attachment from Gmail message"""
    try:
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        
        for part in message['payload'].get('parts', []):
            if part['filename'] == attachment_filename:
                if 'data' in part['body']:
                    return base64.urlsafe_b64decode(part['body']['data'])
                else:
                    attachment_id = part['body'].get('attachmentId')
                    if attachment_id:
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=message_id, id=attachment_id
                        ).execute()
                        return base64.urlsafe_b64decode(attachment['data'])
        return None
    except Exception as e:
        logger.error(f"Failed to get attachment {attachment_filename} from message {message_id}: {e}")
        return None


def get_table_columns(bq_client: bigquery.Client, dataset_id: str, table_id: str) -> List[str]:
    """Get all column names from a BigQuery table"""
    try:
        table_ref = f"{PROJECT_ID}.{dataset_id}.{table_id}"
        table = bq_client.get_table(table_ref)
        columns = [field.name for field in table.schema]
        return columns
    except Exception as e:
        logger.error(f"Error getting columns from {dataset_id}.{table_id}: {e}")
        raise


def get_table_columns_by_ref(bq_client: bigquery.Client, table_ref: str) -> List[str]:
    """Get all column names from a fully-qualified BigQuery table reference."""
    try:
        table = bq_client.get_table(table_ref)
        return [field.name for field in table.schema]
    except Exception as e:
        logger.error(f"Error getting columns from {table_ref}: {e}")
        raise


def build_run_scoped_staging_table_id(config: Dict[str, Any], message_id: str) -> str:
    """Create a run-scoped staging table ID to avoid cross-run WRITE_TRUNCATE races."""
    run_suffix = (_current_run_id or os.urandom(8).hex())[:12]
    clean_message_id = re.sub(r'[^a-zA-Z0-9_]', '_', message_id)[-24:]
    if not clean_message_id:
        clean_message_id = os.urandom(4).hex()
    table_name = f"{config['staging_table']}_run_{run_suffix}_{clean_message_id}"
    return f"{PROJECT_ID}.{config['staging_dataset']}.{table_name}"


def set_temp_table_expiration(bq_client: bigquery.Client, table_ref: str, hours: int = 24) -> None:
    """Set a short expiration on run-scoped staging tables for automatic cleanup."""
    try:
        table = bq_client.get_table(table_ref)
        table.expires = datetime.utcnow() + timedelta(hours=hours)
        bq_client.update_table(table, ["expires"])
    except Exception as e:
        logger.warning(f"Failed to set expiration for {table_ref}: {e}")


def ensure_target_table_columns(
    bq_client: bigquery.Client,
    config: Dict[str, Any],
    staging_columns: List[str],
    staging_table_ref: str,
):
    """Ensure target table has all columns that exist in staging table. Adds columns one at a time for partial success."""
    try:
        target_table_ref = f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
        target_table = bq_client.get_table(target_table_ref)
        existing_columns = [field.name for field in target_table.schema]
        
        # Case-insensitive column comparison
        existing_columns_lower = {col.lower() for col in existing_columns}
        missing_columns = [col for col in staging_columns if col.lower() not in existing_columns_lower]
        
        if not missing_columns:
            logger.info(f"Target table already has all columns.")
            return
        
        logger.info(f"Found {len(missing_columns)} new columns to add: {', '.join(missing_columns)}")
        
        # Get staging table schema to copy field types
        staging_table = bq_client.get_table(staging_table_ref)
        staging_fields = {field.name: field for field in staging_table.schema}
        
        fields_added = 0
        fields_failed = []
        
        # Add columns ONE AT A TIME to ensure partial success even if some already exist
        for col_name in missing_columns:
            try:
                # Get fresh target table for each column addition
                target_table = bq_client.get_table(target_table_ref)
                existing_columns = [field.name for field in target_table.schema]
                
                # Case-insensitive check: does this column now exist?
                existing_lower = {col.lower() for col in existing_columns}
                if col_name.lower() in existing_lower:
                    logger.info(f"Field {col_name} already exists in target (case-insensitive match), skipping.")
                    continue
                
                # Create new schema with just this one field added
                new_schema = list(target_table.schema)
                staging_field = staging_fields.get(col_name)
                if staging_field:
                    new_field = bigquery.SchemaField(
                        name=col_name,
                        field_type=staging_field.field_type,
                        mode='NULLABLE'
                    )
                else:
                    new_field = bigquery.SchemaField(
                        name=col_name,
                        field_type='STRING',
                        mode='NULLABLE'
                    )
                new_schema.append(new_field)
                
                target_table.schema = new_schema
                bq_client.update_table(target_table, ['schema'])
                logger.info(f"Successfully added field {col_name} to target table.")
                fields_added += 1
                
            except Exception as field_error:
                # If the error is about a field already existing, continue (it was added by another process)
                if 'already exists' in str(field_error):
                    logger.info(f"Field {col_name} already exists (concurrent update): {field_error}. Continuing.")
                    fields_added += 1  # Count as successful since field exists
                else:
                    logger.error(f"Failed to add field {col_name}: {field_error}")
                    fields_failed.append(col_name)
                    # Continue to attempt adding remaining fields
        
        logger.info(f"Field addition complete: {fields_added} fields successfully added or confirmed, {len(fields_failed)} failures.")
        if fields_failed:
            logger.warning(f"Fields that failed: {', '.join(fields_failed)}")
        
    except Exception as e:
        logger.error(f"Error ensuring target table columns: {e}")
        raise


def reconcile_merged_primary_keys(
        bq_client: bigquery.Client,
        primary_key: str,
        staging_table_ref: str,
        target_table_ref: str,
) -> Tuple[int, int, int, List[str]]:
        """Verify every distinct source key from staging exists in target after MERGE."""
        sql = f"""
        WITH src AS (
            SELECT DISTINCT {primary_key} AS pk
            FROM `{staging_table_ref}`
            WHERE {primary_key} IS NOT NULL
        ),
        tgt AS (
            SELECT DISTINCT t.{primary_key} AS pk
            FROM `{target_table_ref}` t
            JOIN src s ON t.{primary_key} = s.pk
        ),
        missing AS (
            SELECT pk FROM src
            EXCEPT DISTINCT
            SELECT pk FROM tgt
        )
        SELECT
            (SELECT COUNT(*) FROM src) AS source_key_count,
            (SELECT COUNT(*) FROM tgt) AS target_key_count,
            (SELECT COUNT(*) FROM missing) AS missing_key_count,
            ARRAY(SELECT CAST(pk AS STRING) FROM missing ORDER BY CAST(pk AS STRING) LIMIT 20) AS missing_sample
        """

        job = bq_client.query(sql, job_config=bigquery.QueryJobConfig(use_legacy_sql=False))
        row = next(iter(job.result()), None)
        if row is None:
                return 0, 0, 0, []

        source_key_count = int(row.source_key_count or 0)
        target_key_count = int(row.target_key_count or 0)
        missing_key_count = int(row.missing_key_count or 0)
        missing_sample = list(row.missing_sample or [])
        return source_key_count, target_key_count, missing_key_count, missing_sample


def manage_gmail_labels(service, message_id: str, remove_label_name: str, add_label_name: str):
    """Remove and add labels to Gmail message, and mark as read"""
    try:
        # Get all labels
        labels_result = service.users().labels().list(userId='me').execute()
        labels = {label['name']: label['id'] for label in labels_result.get('labels', [])}
        
        remove_label_id = labels.get(remove_label_name)
        add_label_id = labels.get(add_label_name)
        unread_label_id = labels.get('UNREAD')
        
        # Prepare modifications: remove label, add label, and mark as read
        modifications = {}
        remove_ids = []
        add_ids = []
        
        if remove_label_id:
            remove_ids.append(remove_label_id)
        
        if unread_label_id:
            remove_ids.append(unread_label_id)
        
        if add_label_id:
            add_ids.append(add_label_id)
        
        # Apply all modifications in one call
        if remove_ids or add_ids:
            if remove_ids:
                modifications['removeLabelIds'] = remove_ids
            if add_ids:
                modifications['addLabelIds'] = add_ids
            
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body=modifications
            ).execute()
            logger.info(f"Modified message {message_id}: removed labels {remove_ids}, added labels {add_ids}")
            
    except Exception as e:
        logger.error(f"Failed to manage labels for message {message_id}: {e}")
        raise


def robust_parse_csv(csv_data: bytes) -> List[List[str]]:
    """Parse CSV with multiple encoding attempts"""
    encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
    
    for encoding in encodings:
        try:
            text = csv_data.decode(encoding)
            text = text.lstrip('\ufeff')  # Remove BOM
            
            # Try with different delimiters
            for delimiter in [',', ';', '\t']:
                try:
                    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
                    rows = list(reader)
                    
                    # Validate: at least 2 rows with non-empty headers
                    if len(rows) > 1 and any(h.strip() for h in rows[0]):
                        return rows
                except Exception:
                    continue
        except Exception:
            continue
    
    raise ValueError(f"Could not parse CSV with any encoding/delimiter combination")


def standardize_field_name(header: str, field_map: Dict[str, str]) -> str:
    """Standardize field name using field map"""
    return field_map.get(header.strip(), header.strip().replace(' ', '_'))


def handle_empty_values(value: Any, is_timestamp: bool, is_integer: bool) -> Any:
    """Handle empty values and type conversions"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    
    value_str = str(value).strip()
    
    if is_timestamp:
        # Try multiple timestamp formats
        patterns = [
            (r'^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$', '{3}-{1}-{0}T{3}:{4}:00'),
            (r'^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$', '{0}-{1}-{2}T{3}:{4}:{5}'),
            (r'^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$', '{0}-{1}-{2}T{3}:{4}:00'),
        ]
        
        for pattern, template in patterns:
            match = re.match(pattern, value_str)
            if match:
                groups = match.groups()
                try:
                    # Simple validation
                    datetime.strptime(template.format(*groups), '%Y-%m-%dT%H:%M:%S')
                    return template.format(*groups)
                except ValueError:
                    continue
        return None
    
    if is_integer:
        try:
            return int(value_str)
        except ValueError:
            return None
    
    return value_str


def process_csv_attachment(service, message_id: str, attachment_filename: str, config: Dict[str, Any]) -> Tuple[bool, int]:
    """Process a single CSV attachment"""
    logger.info(f"Processing attachment: {attachment_filename} for config: {config['name']}")
    
    # Get attachment data
    csv_data = get_message_attachment(service, message_id, attachment_filename)
    if not csv_data:
        logger.warning(f"Could not retrieve attachment {attachment_filename}")
        return False, 0
    
    bq_client = get_bq_client()
    staging_table_id = build_run_scoped_staging_table_id(config, message_id)

    try:
        # Parse CSV
        rows = robust_parse_csv(csv_data)
        
        if len(rows) <= 1:
            logger.info(f"CSV has no data rows: {attachment_filename}")
            return False, 0
        
        # Convert to NDJSON
        headers = [standardize_field_name(h, config['field_map']) for h in rows[0]]
        ndjson_lines = []
        
        for row in rows[1:]:
            obj = {}
            for i, header in enumerate(headers):
                value = row[i] if i < len(row) else None
                is_ts = header in config['timestamp_fields']
                is_int = header in config['integer_fields']
                obj[header] = handle_empty_values(value, is_ts, is_int)
            ndjson_lines.append(json.dumps(obj))
        
        ndjson_content = '\n'.join(ndjson_lines)
        
        # Load to run-scoped staging table to avoid concurrent run collisions.
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True
        )
        
        load_job = bq_client.load_table_from_file(
            io.BytesIO(ndjson_content.encode()),
            staging_table_id,
            job_config=job_config
        )
        load_job.result()
        logger.info(f"Loaded data to {staging_table_id}")
        set_temp_table_expiration(bq_client, staging_table_id)
        
        # Get actual columns from staging table after load (dynamic column detection)
        staging_columns = get_table_columns_by_ref(bq_client, staging_table_id)
        logger.info(f"Detected {len(staging_columns)} columns in staging table.")
        
        # Ensure target table has all columns from staging
        ensure_target_table_columns(bq_client, config, staging_columns, staging_table_id)
        
        # Merge into target table using dynamic staging columns with case-insensitive matching
        target_table_id = f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
        target_columns = get_table_columns(bq_client, config['target_dataset'], config['target_table'])
        primary_key = config['primary_key']
        
        logger.info(f"Staging table has {len(staging_columns)} columns, target table has {len(target_columns)} columns.")
        
        # Build a case-insensitive map of target columns for matching
        target_columns_lower = {col.lower(): col for col in target_columns}
        
        # Get all staging columns, using the actual target column name if it exists (case-insensitive)
        merge_columns = []
        for col in staging_columns:
            if col.lower() in target_columns_lower:
                merge_columns.append(target_columns_lower[col.lower()])  # Use the actual target column name
        
        if len(merge_columns) < len(staging_columns):
            missing = [col for col in staging_columns if col.lower() not in target_columns_lower]
            logger.warning(f"Warning: {len(missing)} staging columns not in target: {', '.join(missing)}")
            logger.info(f"Will merge {len(merge_columns)} columns that exist in both tables.")
        
        # Build merge query with dynamic columns from staging
        update_cols = [col for col in merge_columns if col != primary_key]
        update_set = ','.join([f'T.{col} = H.{col}' for col in update_cols])
        insert_cols = ','.join(merge_columns)
        insert_vals = ','.join([f'H.{col}' for col in merge_columns])
        
        merge_query = f"""
        MERGE `{target_table_id}` T
        USING `{staging_table_id}` H
        ON T.{primary_key} = H.{primary_key}
        WHEN MATCHED THEN
            UPDATE SET {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols}) VALUES ({insert_vals})
        """
        
        logger.info(f"Using {len(merge_columns)} columns from staging for merge into {target_table_id}.")
        
        query_config = bigquery.QueryJobConfig(use_legacy_sql=False)
        merge_job = bq_client.query(merge_query, job_config=query_config)
        merge_job.result()

        source_keys, target_keys, missing_keys, missing_sample = reconcile_merged_primary_keys(
            bq_client,
            primary_key,
            staging_table_id,
            target_table_id,
        )
        logger.info(
            "Reconciliation for %s: source_keys=%s target_keys=%s missing=%s",
            config['name'],
            source_keys,
            target_keys,
            missing_keys,
        )
        if missing_keys > 0:
            raise RuntimeError(
                f"Reconciliation failed for {config['name']}: {missing_keys} keys missing after merge. "
                f"Sample: {missing_sample}"
            )
        
        # Extract DML affected rows from statistics (matching GAS script exactly)
        # GAS uses: completedJob.statistics.query.numDmlAffectedRows
        # Python uses: merge_job.num_dml_affected_rows
        rows_affected = merge_job.num_dml_affected_rows or 0
        logger.info(f"Merged data into {target_table_id}. Rows affected: {rows_affected}")
        
        return True, int(rows_affected)
        
    except Exception as e:
        logger.error(f"Error processing CSV {attachment_filename}: {e}")
        return False, 0
    finally:
        try:
            bq_client.delete_table(staging_table_id, not_found_ok=True)
            logger.info(f"Deleted run-scoped staging table {staging_table_id}")
        except NotFound:
            pass
        except Exception as cleanup_error:
            logger.warning(f"Failed to delete staging table {staging_table_id}: {cleanup_error}")


def log_pipeline_run(run_id: str, status: str, log_level: str, message: str, window_start: Optional[str] = None, window_end: Optional[str] = None, rows_merged: Optional[int] = None, error_code: Optional[str] = None, context_obj: Optional[Dict] = None):
    """Log pipeline run to BigQuery using MERGE (identical to GAS script)"""
    try:
        duration_seconds = None
        if (status in ('SUCCESS', 'ERROR')) and _script_start_time:
            duration_seconds = (datetime.utcnow() - _script_start_time).total_seconds()

        # Build MERGE query matching GAS script exactly
        merge_query = f"""
        MERGE `{PROJECT_ID}.{DATASET_ID}.{PIPELINE_RUNS_TABLE}` T
        USING (
            SELECT
                @pipeline AS PipelineName,
                @ws AS WindowStart,
                @we AS WindowEnd,
                @rows AS RowsMerged,
                @level AS LogLevel,
                @msg AS Message,
                @runid AS RunID,
                @status AS Status,
                @err AS ErrorCode,
                @duration AS DurationSeconds,
                CAST(NULL AS JSON) AS Context
        ) S
        ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID
        WHEN MATCHED THEN UPDATE SET
            T.WindowStart = COALESCE(S.WindowStart, T.WindowStart),
            T.WindowEnd   = COALESCE(S.WindowEnd,   T.WindowEnd),
            T.RowsMerged  = COALESCE(S.RowsMerged,  T.RowsMerged),
            T.LogLevel    = COALESCE(S.LogLevel,    T.LogLevel),
            T.Message     = COALESCE(S.Message,     T.Message),
            T.Status      = COALESCE(S.Status,      T.Status),
            T.ErrorCode   = COALESCE(S.ErrorCode,   T.ErrorCode),
            T.DurationSeconds = COALESCE(S.DurationSeconds, T.DurationSeconds),
            T.Context     = COALESCE(S.Context,     T.Context)
        WHEN NOT MATCHED THEN
            INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, DurationSeconds, Context)
            VALUES (CURRENT_TIMESTAMP(), S.PipelineName, S.WindowStart, S.WindowEnd, S.RowsMerged, S.LogLevel, S.Message, S.RunID, S.Status, S.ErrorCode, S.DurationSeconds, S.Context)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("pipeline", "STRING", SCRIPT_NAME),
                bigquery.ScalarQueryParameter("ws", "TIMESTAMP", window_start),
                bigquery.ScalarQueryParameter("we", "TIMESTAMP", window_end),
                bigquery.ScalarQueryParameter("rows", "INT64", rows_merged),
                bigquery.ScalarQueryParameter("level", "STRING", log_level),
                bigquery.ScalarQueryParameter("msg", "STRING", message),
                bigquery.ScalarQueryParameter("runid", "STRING", run_id),
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("err", "STRING", error_code),
                bigquery.ScalarQueryParameter("duration", "FLOAT64", duration_seconds),
            ]
        )

        bq_client = get_bq_client()
        logger.info(f"Logging pipeline run: {status} - {message} (RunID: {run_id})")

        max_attempts = 4
        delay_seconds = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                query_job = bq_client.query(merge_query, job_config=job_config)
                query_job.result(timeout=45)
                logger.info(f"Pipeline run logged successfully. Job ID: {query_job.job_id}")
                return
            except Exception as attempt_error:
                if attempt == max_attempts:
                    raise
                logger.warning(
                    "Pipeline run logging attempt %s/%s failed for RunID %s (%s). Retrying in %.1fs.",
                    attempt,
                    max_attempts,
                    run_id,
                    attempt_error,
                    delay_seconds,
                )
                time.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 2, 8.0)

    except Exception as e:
        logger.warning(f"logPipelineRun failed: {e}")
        logger.warning(f"Stack trace: {str(e)}")


@functions_framework.cloud_event
def process_bq_hdwl_email(cloud_event):
    """Main Cloud Function entry point"""
    global _script_start_time, _current_run_id
    
    _current_run_id = os.urandom(16).hex()
    _script_start_time = datetime.utcnow()
    
    logger.info(f"Starting pipeline run {_current_run_id}")
    log_pipeline_run(_current_run_id, "RUNNING", "INFO", "Pipeline run started", None, None, None, None, None)
    
    try:
        # Decode Pub/Sub message
        pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode()
        message_data = json.loads(pubsub_message)
        
        message_id = message_data.get('messageId')
        logger.info(f"Processing email message: {message_id}")
        
        service = get_gmail_service()
        total_rows_merged = 0
        success_count = 0
        failed_attachments = []
        unmatched_csv_attachments = []
        
        # Get message to find attachments
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        logger.info(f"Message retrieved. Payload parts count: {len(message['payload'].get('parts', []))}")
        
        # Process each CSV attachment
        csv_found = False
        for part in message['payload'].get('parts', []):
            filename = part.get('filename', '').lower()
            logger.info(f"Checking part: filename='{filename}'")
            if filename.endswith('.csv'):
                csv_found = True
                logger.info(f"Found CSV attachment: {filename}")
                # Find matching config
                matched_config = False
                for config in CSV_CONFIGURATIONS:
                    if filename.startswith(config['filename_prefix']):
                        matched_config = True
                        logger.info(f"Matched config: {config['name']}")
                        success, rows = process_csv_attachment(service, message_id, part['filename'], config)
                        logger.info(f"CSV processing result: success={success}, rows={rows}")
                        if success:
                            total_rows_merged += rows
                            success_count += 1
                        else:
                            failed_attachments.append(filename)
                        break
                if not matched_config:
                    logger.warning(f"No matching config for CSV attachment: {filename}")
                    unmatched_csv_attachments.append(filename)
        
        if not csv_found:
            logger.info("No CSV attachments found in message")

        if failed_attachments or unmatched_csv_attachments:
            raise RuntimeError(
                "Attachment processing incomplete. "
                f"Failed: {failed_attachments}; Unmatched: {unmatched_csv_attachments}"
            )

        # Manage labels: remove 'pubsub', add 'ArchivedReports'
        manage_gmail_labels(service, message_id, 'pubsub', 'ArchivedReports')
        
        log_pipeline_run(_current_run_id, "SUCCESS", "INFO", f"Pipeline finished", None, None, total_rows_merged, None, None)
        logger.info(f"Pipeline run {_current_run_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        log_pipeline_run(_current_run_id, "ERROR", "ERROR", str(e), None, None, None, None, None)
        raise
