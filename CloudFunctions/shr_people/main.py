"""
Cloud Function to process SHR People emails from Gmail.
Receives Pub/Sub messages, downloads CSV attachments, processes data,
merges to BigQuery by SRNo, manages labels, and logs pipeline runs.
"""

import base64
import json
import csv
import io
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import functions_framework
from google.oauth2.credentials import Credentials
from google.cloud import secretmanager, bigquery
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"
PIPELINE_RUNS_TABLE = "PipelineRuns"
SCRIPT_NAME = "pubsub - SHRPeople"
ERROR_NOTIFICATION_EMAIL = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com"

# Global tracking for pipeline run timing
_script_start_time = None
_current_run_id = None

# SHR People configuration
SHR_PEOPLE_CONFIG = {
    "name": "SHRPeople",
    "filename_extension": ".csv",
    "staging_dataset": "Staging",
    "staging_table": "SHRPeople",
    "target_dataset": "GSO",
    "target_table": "SHRPeople",
    "primary_key": "SRNo",
    "all_columns": [
        "CustID", "CustName", "SRNo", "Product_Family", "Product_ID",
        "Insight_Circuit_ID", "Circuit_Owner", "ProductDescription", "SR_Status", "RSMName"
    ],
    "legacy_mirror_map": {
        "Product Family": "Product_Family",
        "Product ID": "Product_ID",
        "Insight Circuit ID": "Insight_Circuit_ID",
        "Circuit Owner": "Circuit_Owner",
        "SR Status": "SR_Status"
    },
    "field_map": {
        "CustID": "CustID",
        "CustName": "CustName",
        "SRNo": "SRNo",
        "Product Family": "Product_Family",
        "Product ID": "Product_ID",
        "Insight Circuit ID": "Insight_Circuit_ID",
        "Circuit Owner": "Circuit_Owner",
        "ProductDescription": "ProductDescription",
        "SR Status": "SR_Status",
        "RSM Name": "RSMName",
        "RSMName": "RSMName"
    },
    "timestamp_fields": [],
    "integer_fields": []
}


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
        logger.warning(f"Could not get table columns for {dataset_id}.{table_id}: {e}")
        return []


def ensure_target_table_columns(bq_client: bigquery.Client, dataset_id: str, table_id: str, expected_columns: List[str]):
    """Ensure target table has all expected columns, add missing ones"""
    try:
        existing_columns = get_table_columns(bq_client, dataset_id, table_id)
        missing_columns = [col for col in expected_columns if col not in existing_columns]
        
        if missing_columns:
            logger.info(f"Adding missing columns to {dataset_id}.{table_id}: {missing_columns}")
            table_ref = f"{PROJECT_ID}.{dataset_id}.{table_id}"
            table = bq_client.get_table(table_ref)
            
            new_schema = list(table.schema)
            for col in missing_columns:
                new_schema.append(bigquery.SchemaField(col, "STRING"))
            
            table.schema = new_schema
            bq_client.update_table(table, ["schema"])
            logger.info(f"Successfully added {len(missing_columns)} columns")
    except Exception as e:
        logger.warning(f"Could not ensure target columns: {e}")


def parse_timestamp(value: str) -> Optional[str]:
    """Parse timestamp from various formats to ISO format"""
    if not value or value.strip() == '':
        return None
    
    timestamp_formats = [
        '%Y-%m-%d %H:%M:%S',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %I:%M:%S %p',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d',
        '%m/%d/%Y'
    ]
    
    for fmt in timestamp_formats:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
    
    logger.warning(f"Could not parse timestamp: {value}")
    return None


def clean_rsm_name(value: Optional[str]) -> Optional[str]:
    """Normalize RSM names from formats like 'Last,First,Middle' to 'First Middle Last'."""
    if value is None:
        return None

    cleaned = str(value).strip().strip('"').strip("'").strip()
    if not cleaned:
        return None

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if ',' not in cleaned:
        return cleaned

    parts = [part.strip() for part in cleaned.split(',') if part and part.strip()]
    if len(parts) < 2:
        return cleaned

    # Expected input format: 'Last,First,Middle' or 'Last,First'.
    last_name = parts[0]
    first_name = parts[1]
    middle_name = parts[2] if len(parts) > 2 else ''

    formatted_parts = [part for part in [first_name, middle_name, last_name] if part]
    return ' '.join(formatted_parts) if formatted_parts else cleaned


def clean_quoted_field(value: Optional[str]) -> Optional[str]:
    """Remove leading/trailing double quotes from a string field."""
    if isinstance(value, str):
        return value.strip('"')
    return value


def create_composite_key(row: Dict[str, Any], config: Dict) -> str:
    """Create composite key from row data"""
    primary_key = config.get('primary_key', '')
    if primary_key and primary_key in row:
        return str(row[primary_key])
    
    # Fallback: use first non-empty value
    for key, value in row.items():
        if value:
            return str(value)
    
    return ''


def process_csv_data(csv_content: bytes, config: Dict) -> Tuple[bool, int]:
    """Process CSV data and load to BigQuery staging, then merge to target"""
    try:
        bq_client = bigquery.Client(project=PROJECT_ID)
        
        # Detect encoding
        encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
        csv_text = None
        for encoding in encodings:
            try:
                csv_text = csv_content.decode(encoding)
                logger.info(f"Successfully decoded CSV with {encoding} encoding")
                break
            except UnicodeDecodeError:
                continue
        
        if csv_text is None:
            logger.error("Failed to decode CSV with any encoding")
            return False, 0
        
        # Parse CSV with multiple delimiter attempts
        rows = []
        for delimiter in [',', '\t', ';']:
            try:
                csv_reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)
                rows = [row for row in csv_reader if any(val.strip() for val in row.values())]
                if rows and len(rows[0]) > 1:
                    logger.info(f"Successfully parsed CSV with delimiter '{delimiter}', found {len(rows)} rows")
                    break
            except Exception as e:
                logger.warning(f"Failed to parse with delimiter '{delimiter}': {e}")
                continue
        
        if not rows:
            logger.warning("No data rows found in CSV")
            return False, 0
        
        # Map and transform data
        transformed_rows = []
        field_map = config.get('field_map', {})
        timestamp_fields = config.get('timestamp_fields', [])
        integer_fields = config.get('integer_fields', [])
        primary_key = config.get('primary_key', '')
        
        for row in rows:
            transformed_row = {}
            
            # Map fields
            for source_col, target_col in field_map.items():
                value = (row.get(source_col, '') or '').strip()
                
                # Parse timestamps
                if target_col in timestamp_fields:
                    value = parse_timestamp(value)
                
                # Parse integers
                elif target_col in integer_fields:
                    try:
                        value = int(float(value)) if value else None
                    except ValueError:
                        value = None
                
                elif target_col == 'RSMName':
                    value = clean_rsm_name(value)

                elif target_col in ['CustID', 'CustName']:
                    value = clean_quoted_field(value)
                
                transformed_row[target_col] = value
            
            # Skip rows without primary key
            if primary_key and not transformed_row.get(primary_key):
                continue
            
            # Add composite key
            transformed_row['_composite_key'] = create_composite_key(transformed_row, config)
            
            transformed_rows.append(transformed_row)
        
        if not transformed_rows:
            logger.warning("No valid rows after transformation")
            return False, 0
        
        logger.info(f"Transformed {len(transformed_rows)} rows")
        
        # Convert to NDJSON
        ndjson_content = '\n'.join([json.dumps(row) for row in transformed_rows])
        
        # Load to staging table
        staging_table_id = f"{PROJECT_ID}.{config['staging_dataset']}.{config['staging_table']}"
        
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
        logger.info(f"Loaded {len(transformed_rows)} rows to staging table {staging_table_id}")
        
        # Ensure target table has all necessary columns, including legacy mirrored fields.
        target_columns = list(config['all_columns'])
        legacy_mirror_map = config.get('legacy_mirror_map', {})
        target_columns.extend([col for col in legacy_mirror_map.keys() if col not in target_columns])
        ensure_target_table_columns(bq_client, config['target_dataset'], config['target_table'], target_columns)
        
        # MERGE staging into target
        merge_query = build_merge_query(config)
        logger.info(f"Executing MERGE query")
        
        query_job = bq_client.query(merge_query)
        query_job.result()
        logger.info(f"MERGE completed successfully")
        
        return True, len(transformed_rows)
        
    except Exception as e:
        logger.error(f"Error processing CSV: {e}")
        return False, 0


def build_merge_query(config: Dict) -> str:
    """Build MERGE query to merge staging into target table."""
    staging_table = f"`{PROJECT_ID}.{config['staging_dataset']}.{config['staging_table']}`"
    target_table = f"`{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}`"
    primary_key = config['primary_key']
    all_columns = config['all_columns']
    legacy_mirror_map = config.get('legacy_mirror_map', {})

    def quote_identifier(column_name: str) -> str:
        return f"`{column_name}`"

    # Build deduplicated source
    source_columns = ', '.join(
        [f"CAST({quote_identifier(col)} AS STRING) AS {quote_identifier(col)}" for col in all_columns]
    )

    dedup_source = f"""
    SELECT * FROM (
        SELECT
            {source_columns},
            ROW_NUMBER() OVER (PARTITION BY {quote_identifier(primary_key)} ORDER BY {quote_identifier(primary_key)}) AS rn
        FROM {staging_table}
        WHERE {quote_identifier(primary_key)} IS NOT NULL AND {quote_identifier(primary_key)} != ""
    ) WHERE rn = 1
    """

    # Build UPDATE SET clause
    update_assignments = [
        f"T.{quote_identifier(col)} = S.{quote_identifier(col)}"
        for col in all_columns
        if col != primary_key
    ]
    for legacy_col, source_col in legacy_mirror_map.items():
        update_assignments.append(
            f"T.{quote_identifier(legacy_col)} = S.{quote_identifier(source_col)}"
        )
    update_set = ',\n        '.join(update_assignments)

    # Build INSERT columns and values
    insert_columns = list(all_columns)
    insert_values = [f"S.{quote_identifier(col)}" for col in all_columns]
    for legacy_col, source_col in legacy_mirror_map.items():
        insert_columns.append(legacy_col)
        insert_values.append(f"S.{quote_identifier(source_col)}")

    insert_cols = ', '.join([quote_identifier(col) for col in insert_columns])
    insert_vals = ', '.join(insert_values)

    merge_query = f"""
    MERGE {target_table} T
    USING ({dedup_source}) S
    ON T.{quote_identifier(primary_key)} = S.{quote_identifier(primary_key)}
    WHEN MATCHED THEN UPDATE SET
        {update_set}
    WHEN NOT MATCHED THEN
        INSERT ({insert_cols})
        VALUES ({insert_vals})
    """

    return merge_query


def manage_gmail_labels(service, message_id: str, remove_label: str, add_label: str):
    """Remove and add labels to Gmail message"""
    try:
        # Get label IDs
        labels_result = service.users().labels().list(userId='me').execute()
        labels = labels_result.get('labels', [])
        
        remove_label_id = None
        add_label_id = None
        
        for label in labels:
            if label['name'] == remove_label:
                remove_label_id = label['id']
            elif label['name'] == add_label:
                add_label_id = label['id']
        
        # Modify labels
        body = {
            'removeLabelIds': [remove_label_id] if remove_label_id else [],
            'addLabelIds': [add_label_id] if add_label_id else []
        }
        
        service.users().messages().modify(userId='me', id=message_id, body=body).execute()
        logger.info(f"Labels updated: removed '{remove_label}', added '{add_label}'")
        
    except Exception as e:
        logger.error(f"Failed to manage labels: {e}")


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
                bigquery.ScalarQueryParameter("rows", "INT64", str(rows_merged) if rows_merged is not None else None),
                bigquery.ScalarQueryParameter("level", "STRING", log_level),
                bigquery.ScalarQueryParameter("msg", "STRING", message),
                bigquery.ScalarQueryParameter("runid", "STRING", run_id),
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("err", "STRING", error_code),
                bigquery.ScalarQueryParameter("duration", "FLOAT64", duration_seconds),
            ]
        )

        bq_client = bigquery.Client(project=PROJECT_ID)
        logger.info(f"Logging pipeline run: {status} - {message} (RunID: {run_id})")
        query_job = bq_client.query(merge_query, job_config=job_config)
        query_job.result()
        logger.info(f"Pipeline run logged successfully. Job ID: {query_job.job_id}")

    except Exception as e:
        logger.warning(f"logPipelineRun failed: {e}")
        logger.warning(f"Stack trace: {str(e)}")


@functions_framework.cloud_event
def process_shr_people_email(cloud_event):
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
        
        # Get message to find attachments
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        logger.info(f"Message retrieved. Payload parts count: {len(message['payload'].get('parts', []))}")
        
        # Process CSV attachments
        csv_found = False
        for part in message['payload'].get('parts', []):
            filename = part.get('filename', '').lower()
            logger.info(f"Checking part: filename='{filename}'")
            
            if filename.endswith('.csv'):
                csv_found = True
                logger.info(f"Found CSV attachment: {filename}")
                
                # Get CSV data
                csv_data = get_message_attachment(service, message_id, part['filename'])
                if not csv_data:
                    logger.warning(f"Could not retrieve CSV attachment {filename}")
                    continue
                
                # Process CSV
                success, rows = process_csv_data(csv_data, SHR_PEOPLE_CONFIG)
                logger.info(f"CSV processing result: success={success}, rows={rows}")
                
                if success:
                    total_rows_merged += rows
                    
                    # Warn if approaching 50k row cap
                    if rows >= 47000:
                        warning_msg = f"Row cap warning: '{filename}' returned {rows} rows (cap=50000). Split query required."
                        logger.warning(warning_msg)
                        log_pipeline_run(_current_run_id, "WARNING", "WARN", warning_msg, None, None, rows, "ROW_CAP_WARNING", None)
        
        if not csv_found:
            logger.info("No CSV attachments found in message")
        
        # Manage labels: remove 'pubsub', add 'ArchivedReports'
        manage_gmail_labels(service, message_id, 'pubsub', 'ArchivedReports')
        
        log_pipeline_run(_current_run_id, "SUCCESS", "INFO", f"Pipeline finished", None, None, total_rows_merged, None, None)
        logger.info(f"Pipeline run {_current_run_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        log_pipeline_run(_current_run_id, "ERROR", "ERROR", str(e), None, None, None, None, None)
        raise
