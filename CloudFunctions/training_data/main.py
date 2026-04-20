"""
Cloud Function to process Training Data emails from Gmail.
Receives Pub/Sub messages, downloads ZIP attachments, extracts CSV files,
filters columns, and replaces BigQuery data weekly.
"""

import base64
import json
import csv
import io
import logging
import os
import re
import zipfile
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
SCRIPT_NAME = "pubsub - TrainingData"
ERROR_NOTIFICATION_EMAIL = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com"

# Global tracking for pipeline run timing
_script_start_time = None
_current_run_id = None

# Training Data configuration
TRAINING_DATA_CONFIG = {
    "name": "TrainingData",
    "filename_extension": ".csv",
    "target_dataset": "GSO",
    "target_table": "TrainingData",
    # Only these columns will be extracted from source CSV
    "selected_columns": [
        "First Name", "Last Name", "Middle Name", "User Legal Name", "Email Address",
        "Division", "Department", "Team", "Item Title", "Completion Date"
    ],
    # Map source column names to target BigQuery column names
    "field_map": {
        "First Name": "First_Name",
        "Last Name": "Last_Name",
        "Middle Name": "Middle_Name",
        "User Legal Name": "User_Legal_Name",
        "Email Address": "Email_Address",
        "Division": "Division",
        "Department": "Department",
        "Team": "Team",
        "Item Title": "Item_Title",
        "Completion Date": "Completion_Date"
    },
    "date_fields": ["Completion_Date"],
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


def extract_csv_from_zip(zip_data: bytes) -> Optional[Tuple[str, bytes]]:
    """Extract first CSV file from ZIP archive"""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
            for filename in zip_file.namelist():
                if filename.lower().endswith('.csv'):
                    csv_data = zip_file.read(filename)
                    logger.info(f"Extracted CSV file from ZIP: {filename}")
                    return filename, csv_data
        logger.warning("No CSV file found in ZIP archive")
        return None
    except Exception as e:
        logger.error(f"Failed to extract CSV from ZIP: {e}")
        return None





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


def parse_completion_date(date_str: str) -> Optional[str]:
    """Parse completion date to YYYY-MM-DD format for BigQuery DATE field"""
    if not date_str or not date_str.strip():
        return None
    
    date_str = date_str.strip()
    
    # Try different date formats
    formats = [
        '%b %d, %Y',      # "Jun 25, 2025"
        '%B %d, %Y',      # "June 25, 2025"
        '%m/%d/%Y',       # "06/25/2025"
        '%Y-%m-%d',       # "2025-06-25"
        '%d/%m/%Y',       # "25/06/2025"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    
    logger.warning(f"Could not parse date: {date_str}")
    return None





def process_csv_data(csv_data: bytes, config: Dict[str, Any]) -> Tuple[bool, int]:
    """Process CSV data and load directly to BigQuery (replaces existing data)"""
    logger.info(f"Processing CSV data for {config['name']}")
    
    try:
        # Parse CSV
        rows = robust_parse_csv(csv_data)
        
        if len(rows) <= 1:
            logger.info(f"CSV has no data rows")
            return False, 0
        
        # Get headers and find selected columns
        source_headers = rows[0]
        selected_indices = []
        selected_target_names = []
        
        for col in config['selected_columns']:
            try:
                idx = source_headers.index(col)
                selected_indices.append(idx)
                target_name = config['field_map'].get(col, col.replace(' ', '_'))
                selected_target_names.append(target_name)
                logger.info(f"Mapping column '{col}' (index {idx}) to '{target_name}'")
            except ValueError:
                logger.warning(f"Column '{col}' not found in CSV headers")
        
        if not selected_indices:
            logger.error("No selected columns found in CSV")
            return False, 0
        
        # Convert to NDJSON with only selected columns
        ndjson_lines = []
        
        for row in rows[1:]:
            obj = {}
            
            # Add selected columns
            for i, idx in enumerate(selected_indices):
                target_name = selected_target_names[i]
                value = row[idx] if idx < len(row) else None
                
                # Handle empty values
                if value is None or (isinstance(value, str) and not value.strip()):
                    obj[target_name] = None
                    continue
                
                value_str = str(value).strip()
                
                # Parse date fields
                if target_name in config['date_fields']:
                    obj[target_name] = parse_completion_date(value_str)
                # Parse integer fields
                elif target_name in config['integer_fields']:
                    try:
                        obj[target_name] = int(value_str)
                    except ValueError:
                        obj[target_name] = None
                else:
                    obj[target_name] = value_str
            
            ndjson_lines.append(json.dumps(obj))
        
        ndjson_content = '\n'.join(ndjson_lines)
        row_count = len(ndjson_lines)
        
        # Load directly to BigQuery target table (truncate and replace)
        bq_client = bigquery.Client(project=PROJECT_ID)
        target_table_id = f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
        
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,  # Replace all data
            autodetect=False,
            schema=[
                bigquery.SchemaField("First_Name", "STRING"),
                bigquery.SchemaField("Last_Name", "STRING"),
                bigquery.SchemaField("Middle_Name", "STRING"),
                bigquery.SchemaField("User_Legal_Name", "STRING"),
                bigquery.SchemaField("Email_Address", "STRING"),
                bigquery.SchemaField("Division", "STRING"),
                bigquery.SchemaField("Department", "STRING"),
                bigquery.SchemaField("Team", "STRING"),
                bigquery.SchemaField("Item_Title", "STRING"),
                bigquery.SchemaField("Completion_Date", "DATE"),
            ]
        )
        
        load_job = bq_client.load_table_from_file(
            io.BytesIO(ndjson_content.encode()),
            target_table_id,
            job_config=job_config
        )
        load_job.result()
        logger.info(f"Loaded {row_count} rows to {target_table_id} (replaced all existing data)")
        
        return True, row_count
        
    except Exception as e:
        logger.error(f"Error processing CSV: {e}")
        return False, 0


def log_pipeline_run(run_id: str, status: str, log_level: str, message: str, window_start: Optional[str] = None, window_end: Optional[str] = None, rows_merged: Optional[int] = None, error_code: Optional[str] = None, context_obj: Optional[Dict] = None):
    """Log pipeline run to BigQuery using MERGE"""
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
def process_training_data_email(cloud_event):
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
        
        # Process ZIP attachments
        zip_found = False
        for part in message['payload'].get('parts', []):
            filename = part.get('filename', '').lower()
            logger.info(f"Checking part: filename='{filename}'")
            
            if filename.endswith('.zip'):
                zip_found = True
                logger.info(f"Found ZIP attachment: {filename}")
                
                # Get ZIP data
                zip_data = get_message_attachment(service, message_id, part['filename'])
                if not zip_data:
                    logger.warning(f"Could not retrieve ZIP attachment {filename}")
                    continue
                
                # Extract CSV from ZIP
                csv_result = extract_csv_from_zip(zip_data)
                if not csv_result:
                    logger.warning(f"No CSV found in ZIP {filename}")
                    continue
                
                csv_filename, csv_data = csv_result
                logger.info(f"Processing extracted CSV: {csv_filename}")
                
                # Process CSV
                success, rows = process_csv_data(csv_data, TRAINING_DATA_CONFIG)
                logger.info(f"CSV processing result: success={success}, rows={rows}")
                
                if success:
                    total_rows_merged += rows
        
        if not zip_found:
            logger.info("No ZIP attachments found in message")
        
        # Manage labels: remove 'pubsub', add 'ArchivedReports'
        manage_gmail_labels(service, message_id, 'pubsub', 'ArchivedReports')
        
        log_pipeline_run(_current_run_id, "SUCCESS", "INFO", f"Pipeline finished", None, None, total_rows_merged, None, None)
        logger.info(f"Pipeline run {_current_run_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        log_pipeline_run(_current_run_id, "ERROR", "ERROR", str(e), None, None, None, None, None)
        raise
