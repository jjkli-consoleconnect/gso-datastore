"""
Cloud Function: SRInventory
Receives Pub/Sub messages published by gmail_checker, downloads matching Excel
attachments from Gmail, and appends rows to BigQuery table GSO.SRInventory.

Adds DateInserted (DATE) derived from subject/filename date token (YYYYMMDD).
"""

import base64
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
import openpyxl
from google.cloud import bigquery, secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

# Consistent logging style with other modern pipelines
setup_root_logging()

PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"
TABLE_ID = "SRInventory"
PIPELINE_NAME = "pubsub - SRInventory"
SUBJECT_PREFIX = "TIP GCSC Region detail"
GMAIL_LABEL_TO_REMOVE = "pubsub"
GMAIL_LABEL_TO_ADD = "ArchivedReports"


def load_oauth_credentials() -> Credentials:
    """Load Gmail OAuth credentials from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    secret_name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-token/versions/latest"
    response = client.access_secret_version(request={"name": secret_name})
    token_data = json.loads(response.payload.data.decode("utf-8"))
    return Credentials.from_authorized_user_info(token_data)


def get_gmail_service():
    """Create Gmail API client."""
    creds = load_oauth_credentials()
    return build("gmail", "v1", credentials=creds)


def parse_pubsub_message_data(cloud_event) -> Dict[str, Any]:
    """Parse Pub/Sub payload from CloudEvent into a dict."""
    data = cloud_event.data or {}

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
            candidates.append(base64.b64decode(raw_payload).decode("utf-8", errors="replace"))
        except Exception:
            pass

    for candidate in candidates:
        text = (candidate or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    raise ValueError(f"Unable to parse Pub/Sub payload. Raw: {str(raw_payload)[:300]}")


def _flatten_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten potentially nested Gmail payload parts."""
    out: List[Dict[str, Any]] = []
    stack = [payload]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        parts = node.get("parts") or []
        if isinstance(parts, list):
            stack.extend(parts)
        if node.get("filename"):
            out.append(node)
    return out


def get_message_metadata(service, message_id: str) -> Tuple[str, str]:
    """Return subject and sender for the Gmail message."""
    message = service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["Subject", "From"],
    ).execute()

    headers = message.get("payload", {}).get("headers", [])
    subject = next((h.get("value", "") for h in headers if h.get("name", "").lower() == "subject"), "")
    sender = next((h.get("value", "") for h in headers if h.get("name", "").lower() == "from"), "")
    return subject, sender


def list_excel_attachments(service, message_id: str) -> List[str]:
    """List .xlsx attachment names in a Gmail message."""
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = message.get("payload", {})
    parts = _flatten_parts(payload)
    names: List[str] = []
    for part in parts:
        filename = (part.get("filename") or "").strip()
        if filename.lower().endswith(".xlsx"):
            names.append(filename)
    return names


def get_message_attachment(service, message_id: str, attachment_filename: str) -> Optional[bytes]:
    """Download a single attachment from Gmail message by filename."""
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = message.get("payload", {})

    for part in _flatten_parts(payload):
        if (part.get("filename") or "") != attachment_filename:
            continue

        body = part.get("body", {})
        if "data" in body:
            return base64.urlsafe_b64decode(body["data"])

        attachment_id = body.get("attachmentId")
        if attachment_id:
            attachment = service.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id,
            ).execute()
            return base64.urlsafe_b64decode(attachment["data"])

    return None


def parse_date_from_subject_or_filename(subject: str, filename: str) -> str:
    """
    Parse YYYYMMDD date from subject first, then filename.
    Returns YYYY-MM-DD (BigQuery DATE string).
    """
    candidates = [subject or "", filename or ""]
    for text in candidates:
        match = re.search(r"(\d{8})", text)
        if not match:
            continue
        try:
            dt = datetime.strptime(match.group(1), "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(
        "Could not find valid YYYYMMDD date in subject or filename. "
        f"subject='{subject}', filename='{filename}'"
    )


def sanitize_column_name(name: Any, idx: int) -> str:
    """Convert source headers into BigQuery-safe column names."""
    raw = str(name).strip() if name is not None else ""
    if not raw:
        raw = f"Column_{idx + 1}"

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")

    if not cleaned:
        cleaned = f"Column_{idx + 1}"
    if cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"

    return cleaned[:300]


def parse_excel_rows(excel_bytes: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Parse first sheet from XLSX.
    Returns sanitized header list and row dicts (all cell values cast to STRING).
    """
    workbook = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True, read_only=True)
    sheet = workbook.active

    rows = sheet.iter_rows(values_only=True)
    header_row = next(rows, None)
    if not header_row:
        return [], []

    base_headers = [sanitize_column_name(h, i) for i, h in enumerate(header_row)]

    # De-duplicate repeated columns after sanitization
    seen: Dict[str, int] = {}
    headers: List[str] = []
    for h in base_headers:
        c = seen.get(h, 0)
        if c == 0:
            headers.append(h)
        else:
            headers.append(f"{h}_{c + 1}")
        seen[h] = c + 1

    parsed_rows: List[Dict[str, Any]] = []
    for row in rows:
        row_obj: Dict[str, Any] = {}
        non_empty = False
        for i, header in enumerate(headers):
            value = row[i] if i < len(row) else None
            if value is None:
                row_obj[header] = None
                continue
            text_value = str(value).strip()
            row_obj[header] = text_value if text_value != "" else None
            if row_obj[header] is not None:
                non_empty = True

        if non_empty:
            parsed_rows.append(row_obj)

    return headers, parsed_rows


def ensure_table_and_columns(
    bq_client: bigquery.Client,
    dataset_id: str,
    table_id: str,
    source_headers: List[str],
) -> None:
    """Create table if missing and add any new source columns as STRING."""
    table_ref = f"{PROJECT_ID}.{dataset_id}.{table_id}"

    required_schema = [bigquery.SchemaField(name, "STRING") for name in source_headers]
    required_schema.append(bigquery.SchemaField("DateInserted", "DATE"))

    try:
        table = bq_client.get_table(table_ref)
        existing = [field.name for field in table.schema]
        existing_lower = {name.lower() for name in existing}

        missing_fields: List[bigquery.SchemaField] = []
        for field in required_schema:
            if field.name.lower() not in existing_lower:
                missing_fields.append(field)

        if missing_fields:
            table.schema = list(table.schema) + missing_fields
            bq_client.update_table(table, ["schema"])
            logging.info(f"Added {len(missing_fields)} new columns to {table_ref}")
    except Exception as exc:
        if "Not found" in str(exc) or "404" in str(exc):
            table = bigquery.Table(table_ref, schema=required_schema)
            bq_client.create_table(table)
            logging.info(f"Created table {table_ref}")
        else:
            raise


def manage_gmail_labels(service, message_id: str, remove_label_name: str, add_label_name: str) -> None:
    """Remove source label and unread, and add archive label."""
    labels_result = service.users().labels().list(userId="me").execute()
    labels = {label["name"]: label["id"] for label in labels_result.get("labels", [])}

    remove_ids: List[str] = []
    add_ids: List[str] = []

    if remove_label_name in labels:
        remove_ids.append(labels[remove_label_name])
    if "UNREAD" in labels:
        remove_ids.append(labels["UNREAD"])
    if add_label_name in labels:
        add_ids.append(labels[add_label_name])

    body: Dict[str, List[str]] = {}
    if remove_ids:
        body["removeLabelIds"] = remove_ids
    if add_ids:
        body["addLabelIds"] = add_ids

    if body:
        service.users().messages().modify(userId="me", id=message_id, body=body).execute()


def cleanup_stale_running(client: bigquery.Client) -> None:
    """Mark stale RUNNING rows for this pipeline as ERROR."""
    cleanup_query = f"""
        UPDATE `{DATASET_ID}.PipelineRuns`
        SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
        WHERE PipelineName = '{PIPELINE_NAME}'
          AND Status = 'RUNNING'
          AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
    """
    client.query(cleanup_query).result()


@functions_framework.cloud_event
def process_sr_inventory_email(cloud_event):
    """Pub/Sub-triggered entrypoint for SRInventory ingestion."""
    run_id = str(uuid.uuid4())
    run_started = datetime.now(timezone.utc)

    client = bigquery.Client(project=PROJECT_ID)

    try:
        cleanup_stale_running(client)
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    log_pipeline_run(
        client,
        pipeline_name=PIPELINE_NAME,
        run_id=run_id,
        level="INFO",
        message="Pipeline started",
        status="RUNNING",
    )

    rows_inserted = 0

    try:
        message_data = parse_pubsub_message_data(cloud_event)
        message_id = message_data.get("messageId") or message_data.get("message_id")
        if not message_id:
            raise ValueError("Pub/Sub payload missing messageId")

        gmail = get_gmail_service()
        subject, sender = get_message_metadata(gmail, message_id)
        logging.info(f"Processing Gmail message {message_id} from '{sender}' with subject '{subject}'")

        if SUBJECT_PREFIX.lower() not in (subject or "").lower():
            raise ValueError(
                f"Message subject does not match expected prefix '{SUBJECT_PREFIX}': '{subject}'"
            )

        attachment_names = list_excel_attachments(gmail, message_id)
        if not attachment_names:
            raise ValueError("No .xlsx attachment found in message")

        bq_rows: List[Dict[str, Any]] = []
        all_headers: List[str] = []

        for attachment_name in attachment_names:
            attachment_data = get_message_attachment(gmail, message_id, attachment_name)
            if not attachment_data:
                logging.warning(f"Could not download attachment: {attachment_name}")
                continue

            date_inserted = parse_date_from_subject_or_filename(subject, attachment_name)
            headers, data_rows = parse_excel_rows(attachment_data)
            if not headers:
                logging.warning(f"Attachment has no headers: {attachment_name}")
                continue

            all_headers = list(dict.fromkeys(all_headers + headers))

            for row in data_rows:
                row["DateInserted"] = date_inserted
                bq_rows.append(row)

        if not bq_rows:
            raise ValueError("No data rows parsed from Excel attachments")

        ensure_table_and_columns(client, DATASET_ID, TABLE_ID, all_headers)

        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
        table = client.get_table(table_ref)
        load_config = bigquery.LoadJobConfig(
            schema=table.schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        load_job = client.load_table_from_json(bq_rows, table_ref, job_config=load_config)
        load_job.result()

        rows_inserted = len(bq_rows)
        manage_gmail_labels(gmail, message_id, GMAIL_LABEL_TO_REMOVE, GMAIL_LABEL_TO_ADD)

        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(
            client,
            pipeline_name=PIPELINE_NAME,
            run_id=run_id,
            level="INFO",
            message=f"Pipeline finished. Inserted {rows_inserted} rows",
            status="SUCCESS",
            window_start=run_started,
            window_end=run_ended,
            rows_merged=rows_inserted,
            duration_seconds=duration_seconds,
        )

    except Exception as e:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        log_pipeline_run(
            client,
            pipeline_name=PIPELINE_NAME,
            run_id=run_id,
            level="ERROR",
            message=f"Exception: {e}",
            status="ERROR",
            error_code=getattr(e, "code", None),
            duration_seconds=duration_seconds,
        )
        raise
