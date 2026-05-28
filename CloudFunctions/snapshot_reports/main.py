"""
Cloud Function to process Snapshot Reports emails from Gmail.
Receives Pub/Sub messages, downloads Escalation and Outstanding snapshot attachments,
processes CSV files, loads to BigQuery, manages labels, and logs pipeline runs.
"""

import base64
import json
import ast
import csv
import io
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

import functions_framework
from google.oauth2.credentials import Credentials
from google.cloud import secretmanager, pubsub_v1, bigquery
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "Snapshot"
PIPELINE_RUNS_TABLE = "PipelineRuns"
SCRIPT_NAME = "pubsub - Snapshot Reports"
ERROR_NOTIFICATION_EMAIL = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com"
GMAIL_LABEL_TO_REMOVE = "pubsub"

# Global tracking for pipeline run timing
_script_start_time = None
_current_run_id = None

# CSV type configurations
CSV_CONFIGURATIONS = [
    {
        "name": "Escalation",
        "filename_pattern": r"^Escalation.*\.csv$",
        "dataset": "Snapshot",
        "table": "RemedyEscalationSnapshot",
        "required": True
    },
    {
        "name": "Outstanding",
        "filename_pattern": r"^OutstandingSnapshots.*\.csv$",
        "dataset": "Snapshot",
        "table": "RemedyOutstandingSnapshot",
        "required": True
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
        
        # Check all parts recursively
        parts = message['payload'].get('parts', [])
        if not parts and 'body' in message['payload']:
            # Single-part message
            parts = [message['payload']]
        
        for part in parts:
            if part.get('filename') == attachment_filename:
                if 'data' in part.get('body', {}):
                    return base64.urlsafe_b64decode(part['body']['data'])
                else:
                    attachment_id = part.get('body', {}).get('attachmentId')
                    if attachment_id:
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=message_id, id=attachment_id
                        ).execute()
                        return base64.urlsafe_b64decode(attachment['data'])
        
        logger.warning(f"Attachment {attachment_filename} not found in message {message_id}")
        return None
    except Exception as e:
        logger.error(f"Failed to get attachment {attachment_filename} from message {message_id}: {e}")
        return None


def list_message_attachments(service, message_id: str) -> List[str]:
    """List all attachment filenames in a Gmail message"""
    try:
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        attachments = []
        
        parts = message['payload'].get('parts', [])
        if not parts and 'body' in message['payload']:
            parts = [message['payload']]
        
        for part in parts:
            filename = part.get('filename', '')
            if filename:
                attachments.append(filename)
        
        return attachments
    except Exception as e:
        logger.error(f"Failed to list attachments for message {message_id}: {e}")
        return []


def is_json_error_payload(content: bytes) -> bool:
    """Check if content is a JSON error payload instead of CSV"""
    try:
        text = content.decode('utf-8', errors='ignore').strip()
        if text.startswith('{') and '"statusCode"' in text and '"error"' in text:
            logger.warning(f"Detected JSON error payload: {text[:200]}")
            return True
        return False
    except Exception:
        return False


def normalize_column_name(name: str, index: int) -> str:
    """Normalize column name for BigQuery compatibility"""
    # Remove BOM, trim, lowercase
    normalized = name.replace('\ufeff', '').strip().lower()
    # Replace invalid characters with underscore
    normalized = re.sub(r'[^a-z0-9_]', '_', normalized)
    # Remove consecutive underscores
    normalized = re.sub(r'_+', '_', normalized)
    # Remove leading/trailing underscores
    normalized = normalized.strip('_')
    # If empty, use column index
    if not normalized:
        normalized = f'column_{index}'
    # Ensure it starts with letter or underscore
    if normalized and not re.match(r'^[a-z_]', normalized):
        normalized = f'f_{normalized}'
    # Limit to 128 characters
    return normalized[:128]


def get_csv_headers(csv_content: bytes) -> List[str]:
    """Extract and normalize CSV headers"""
    try:
        text = csv_content.decode('utf-8-sig', errors='replace')
        reader = csv.reader(io.StringIO(text))
        raw_headers = next(reader)
        return [normalize_column_name(h, i+1) for i, h in enumerate(raw_headers)]
    except Exception as e:
        logger.error(f"Failed to parse CSV headers: {e}")
        raise


def ensure_bq_table_has_columns(bq_client: bigquery.Client, dataset_id: str, table_id: str, csv_headers: List[str]):
    """Ensure BigQuery table has all columns from CSV headers. Adds missing columns as STRING."""
    try:
        table_ref = f"{PROJECT_ID}.{dataset_id}.{table_id}"
        table = bq_client.get_table(table_ref)
        existing_columns_lower = {field.name.lower() for field in table.schema}
        
        missing_columns = [col for col in csv_headers if col.lower() not in existing_columns_lower]
        
        if not missing_columns:
            logger.info(f"Table {table_id} already has all required columns")
            return
        
        logger.info(f"Adding {len(missing_columns)} new columns to {table_id}: {', '.join(missing_columns)}")
        
        # Add columns one at a time for partial success
        for col_name in missing_columns:
            try:
                table = bq_client.get_table(table_ref)
                existing_lower = {field.name.lower() for field in table.schema}
                
                if col_name.lower() in existing_lower:
                    continue
                
                new_schema = list(table.schema)
                new_schema.append(bigquery.SchemaField(col_name, 'STRING', mode='NULLABLE'))
                table.schema = new_schema
                bq_client.update_table(table, ['schema'])
                logger.info(f"Added column {col_name} to {table_id}")
            except Exception as e:
                logger.error(f"Failed to add column {col_name}: {e}")
        
    except Exception as e:
        logger.error(f"Error ensuring table columns: {e}")
        # Don't raise - allow load to continue with existing schema
        logger.warning("Continuing with existing table schema")


def load_csv_to_bigquery(bq_client: bigquery.Client, csv_content: bytes, dataset_id: str, table_id: str, config_name: str) -> int:
    """Load CSV content to BigQuery table. Returns row count."""
    try:
        # Get headers and ensure table has columns
        headers = get_csv_headers(csv_content)
        ensure_bq_table_has_columns(bq_client, dataset_id, table_id, headers)
        
        # Configure load job
        table_ref = f"{PROJECT_ID}.{dataset_id}.{table_id}"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            allow_quoted_newlines=True,
            allow_jagged_rows=True,
            ignore_unknown_values=True,
            max_bad_records=100,
            autodetect=False
        )
        
        # Load data
        load_job = bq_client.load_table_from_file(
            io.BytesIO(csv_content),
            table_ref,
            job_config=job_config
        )
        
        # Wait for completion
        load_job.result()
        
        # Get row count
        destination_table = bq_client.get_table(table_ref)
        rows_loaded = load_job.output_rows or 0
        
        logger.info(f"Loaded {rows_loaded} rows to {dataset_id}.{table_id} for {config_name}")
        return rows_loaded
        
    except Exception as e:
        logger.error(f"Failed to load CSV to BigQuery for {config_name}: {e}")
        if hasattr(e, 'errors'):
            logger.error(f"BigQuery errors: {e.errors}")
        raise


def mark_message_read_and_remove_label(service, message_id: str):
    """Mark Gmail message as read and remove label"""
    try:
        # Mark as read
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        logger.info(f"Marked message {message_id} as read")
        
        # Remove Dashboard/AutoReports label
        try:
            labels = service.users().labels().list(userId='me').execute().get('labels', [])
            label_id = None
            for label in labels:
                if label['name'] == GMAIL_LABEL_TO_REMOVE:
                    label_id = label['id']
                    break
            
            if label_id:
                service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': [label_id]}
                ).execute()
                logger.info(f"Removed label {GMAIL_LABEL_TO_REMOVE} from message {message_id}")
        except Exception as e:
            logger.warning(f"Failed to remove label: {e}")
            
    except Exception as e:
        logger.error(f"Failed to mark message as read: {e}")


def log_pipeline_run(bq_client: bigquery.Client, run_id: str, status: str, rows_processed: int, error_message: Optional[str] = None):
    """Log pipeline run to PipelineRuns table"""
    try:
        global _script_start_time
        end_time = datetime.utcnow()
        duration_seconds = (end_time - _script_start_time).total_seconds() if _script_start_time else 0
        
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{PIPELINE_RUNS_TABLE}"
        rows_to_insert = [{
            "RunID": run_id,
            "ScriptName": SCRIPT_NAME,
            "StartTime": _script_start_time.isoformat() if _script_start_time else end_time.isoformat(),
            "EndTime": end_time.isoformat(),
            "Status": status,
            "RowsProcessed": rows_processed,
            "ErrorMessage": error_message,
            "DurationSeconds": duration_seconds
        }]
        
        errors = bq_client.insert_rows_json(table_ref, rows_to_insert)
        if errors:
            logger.error(f"Failed to log pipeline run: {errors}")
        else:
            logger.info(f"Logged pipeline run {run_id} with status {status}")
            
    except Exception as e:
        logger.error(f"Error logging pipeline run: {e}")


def send_error_notification(subject: str, body: str):
    """Send error notification to Slack via email"""
    try:
        # Alert emailing is disabled; keep logging only.
        logger.error(f"ERROR NOTIFICATION: {subject}\n{body}")
        # TODO: Implement actual email sending if needed
    except Exception as e:
        logger.error(f"Failed to send error notification: {e}")


def parse_pubsub_message_data(cloud_event) -> Dict[str, Any]:
    """Parse Pub/Sub payload across possible CloudEvent delivery formats."""
    data = cloud_event.data or {}

    # Some wrappers may already provide parsed message fields directly.
    if isinstance(data, dict) and (data.get("messageId") or data.get("message_id")):
        return data

    message_obj = data.get("message", {}) if isinstance(data, dict) else {}
    raw_payload = message_obj.get("data") if isinstance(message_obj, dict) else None

    candidates: List[str] = []
    if isinstance(raw_payload, (bytes, bytearray)):
        candidates.append(raw_payload.decode("utf-8", errors="replace"))
    elif isinstance(raw_payload, str):
        candidates.append(raw_payload)
        try:
            decoded = base64.b64decode(raw_payload).decode("utf-8", errors="replace")
            candidates.append(decoded)
        except Exception:
            pass

    for candidate in candidates:
        text = (candidate or "").strip()
        if not text:
            continue

        # Preferred path: strict JSON payload.
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Compatibility path: Python dict string with single quotes.
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Compatibility path: pseudo-JSON like
        # {messageId:123,subject:pubsub - BQ - Snapshot by Shift,from:user@example.com}
        if text.startswith("{") and text.endswith("}") and ":" in text:
            inner = text[1:-1]
            pairs = re.findall(r'([A-Za-z0-9_]+)\s*:\s*([^,{}]+)', inner)
            if pairs:
                parsed = {k: v.strip() for k, v in pairs}
                if parsed:
                    return parsed

    raise ValueError(f"Unable to parse Pub/Sub payload. Raw message data: {str(raw_payload)[:300]}")


@functions_framework.cloud_event
def process_snapshot_report(cloud_event):
    """
    Main Cloud Function entry point.
    Triggered by Pub/Sub message containing Gmail message ID.
    """
    global _script_start_time, _current_run_id
    _script_start_time = datetime.utcnow()
    _current_run_id = f"{SCRIPT_NAME}_{_script_start_time.strftime('%Y%m%d_%H%M%S')}"
    
    try:
        # Parse Pub/Sub message
        message_data = parse_pubsub_message_data(cloud_event)
        # Accept both keys for compatibility with different publisher versions.
        message_id = message_data.get('message_id') or message_data.get('messageId')
        
        logger.info(f"Processing snapshot report for Gmail message {message_id}")
        
        # Initialize clients
        gmail_service = get_gmail_service()
        bq_client = bigquery.Client(project=PROJECT_ID)
        
        # List all attachments in message
        all_attachments = list_message_attachments(gmail_service, message_id)
        logger.info(f"Found {len(all_attachments)} attachments: {all_attachments}")
        
        total_rows = 0
        configs_processed = 0
        error_payloads_found = 0
        
        # Process each CSV configuration
        for config in CSV_CONFIGURATIONS:
            # Find matching attachment
            matching_attachment = None
            for attachment_name in all_attachments:
                if re.match(config['filename_pattern'], attachment_name, re.IGNORECASE):
                    matching_attachment = attachment_name
                    break
            
            if not matching_attachment:
                if config.get('required'):
                    logger.warning(f"Required attachment not found for {config['name']}")
                continue
            
            logger.info(f"Processing {config['name']}: {matching_attachment}")
            
            # Download attachment
            attachment_content = get_message_attachment(gmail_service, message_id, matching_attachment)
            
            if not attachment_content:
                logger.error(f"Failed to download attachment {matching_attachment}")
                continue
            
            # Check for JSON error payload
            if is_json_error_payload(attachment_content):
                logger.warning(f"Attachment {matching_attachment} is a JSON error payload, skipping")
                error_payloads_found += 1
                send_error_notification(
                    f"Snapshot Report Error Payload: {config['name']}",
                    f"Message {message_id} contained error payload instead of CSV for {matching_attachment}"
                )
                continue
            
            # Load to BigQuery
            try:
                rows = load_csv_to_bigquery(
                    bq_client,
                    attachment_content,
                    config['dataset'],
                    config['table'],
                    config['name']
                )
                total_rows += rows
                configs_processed += 1
            except Exception as e:
                logger.error(f"Failed to load {config['name']}: {e}")
                raise
        
        # If all expected attachments were error payloads, still mark as read
        if error_payloads_found > 0 and configs_processed == 0:
            logger.info("All expected attachments were error payloads - marking message as read")
            mark_message_read_and_remove_label(gmail_service, message_id)
            log_pipeline_run(bq_client, _current_run_id, "SKIPPED_ERROR_PAYLOADS", 0, "All attachments were error payloads")
            return
        
        # Mark message as processed
        if configs_processed > 0:
            mark_message_read_and_remove_label(gmail_service, message_id)
            log_pipeline_run(bq_client, _current_run_id, "SUCCESS", total_rows)
            logger.info(f"Successfully processed {configs_processed} CSV files with {total_rows} total rows")
        else:
            error_msg = "No valid CSV files found in message"
            log_pipeline_run(bq_client, _current_run_id, "FAILED", 0, error_msg)
            send_error_notification(f"Snapshot Report Failed", error_msg)
            raise Exception(error_msg)
        
    except Exception as e:
        logger.error(f"Error processing snapshot report: {e}", exc_info=True)
        if _current_run_id:
            try:
                bq_client = bigquery.Client(project=PROJECT_ID)
                log_pipeline_run(bq_client, _current_run_id, "FAILED", 0, str(e))
            except:
                pass
        send_error_notification(
            f"Snapshot Report Pipeline Failed",
            f"Error: {str(e)}\nRun ID: {_current_run_id}"
        )
        raise
