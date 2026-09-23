"""
Cloud Function to process BigQuery HDWL emails from Gmail.
Receives Pub/Sub messages, downloads attachments, processes CSV files,
loads to BigQuery, manages labels, and logs pipeline runs.
"""

import base64
import ast
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
from google.api_core.exceptions import NotFound, BadRequest
from google.oauth2.credentials import Credentials
from google.cloud import secretmanager, bigquery
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"
PIPELINE_RUNS_TABLE = "PipelineRuns"
SCRIPT_NAME = "pubsub - HDWL"
ERROR_NOTIFICATION_EMAIL = (
    "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com"
)
MIN_VALID_CSV_DATA_ROWS = 3

# Maximum share of candidate rows allowed to have an unexpected column count
# before the attachment is treated as structurally broken (vs. the known
# forwarded-email wrapper noise, which only contaminates a few lines).
MAX_RAGGED_ROW_RATIO = 0.25

# Columns stored as ARRAY<STRING> in target tables; staging rows (one per
# related item) are aggregated into arrays per primary key at merge time.
ARRAY_COLUMNS = [
    "RelatedItemRequestID",
    "RelatedItemDescription",
    "RelatedItemRelatedTicketID",
    "RelatedItemAssociationType",
]

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
            "Incident_Number",
            "Status",
            "CaseType",
            "Assigned_Group",
            "Categorization_Tier_1",
            "Categorization_Tier_2",
            "Categorization_Tier_3",
            "GCSC_1st_Customer_Update",
            "GCSC_2nd_Customer_Update",
            "GCSC_3rd_Customer_Update",
            "Initial_Response_Time",
            "Second_Response_Time",
            "Third_Response_Time",
            "Prod_ID",
            "Fault_Cause",
            "Closed_Date",
            "Submit_Date",
            "Assignee",
            "Closed_By",
            "Submitter",
            "TrueMTTR_mins",
            "Cust_ID",
            "Carrier",
            "Customer_Name",
            "SRno",
            "LastResolvedDate",
            "ReportedDate",
            "RespondedDate",
            "FaultCauseDetail",
            "LastModifiedDate",
            "ReportedBy",
            "Product_Family",
            "ProductDescription",
            "GSMP_Circuit_ID",
            "Urgency",
            "Priority",
            "RSMName",
            "Summary",
            "Fault_Location",
            "Service_Type",
            "Destination",
            "RelatedItemRequestID",
            "RelatedItemDescription",
            "RelatedItemRelatedTicketID",
            "RelatedItemAssociationType",
        ],
        "field_map": {
            "Request ID": "RelatedItemRequestID",
            "Description": "RelatedItemDescription",
            "Related_Ticket_ID": "RelatedItemRelatedTicketID",
            "Association Type": "RelatedItemAssociationType",
            "IncidentNumber": "Incident_Number",
            "casetype": "CaseType",
            "Assigned Group": "Assigned_Group",
            "Categorization Tier 1": "Categorization_Tier_1",
            "Categorization Tier 2": "Categorization_Tier_2",
            "Categorization Tier 3": "Categorization_Tier_3",
            "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
            "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update",
            "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
            "Initial Response Time": "Initial_Response_Time",
            "Second Response Time": "Second_Response_Time",
            "Third Response Time": "Third_Response_Time",
            "Prod ID": "Prod_ID",
            "FaultCause": "Fault_Cause",
            "Closed Date": "Closed_Date",
            "Submit Date": "Submit_Date",
            "ClosedBy": "Closed_By",
            "Cust ID": "Cust_ID",
            "CustomerName": "Customer_Name",
            "SRno": "SRno",
            "SRNo": "SRno",
            "ReportedBy": "ReportedBy",
            "Product Family": "Product_Family",
            "ProductDescription": "ProductDescription",
            "GSMP Circuit ID": "GSMP_Circuit_ID",
            "RSM Name": "RSMName",
            "Summary": "Summary",
            "Fault Location": "Fault_Location",
            "Service Type": "Service_Type",
            "Destination": "Destination",
        },
        "timestamp_fields": [
            "GCSC_1st_Customer_Update",
            "GCSC_2nd_Customer_Update",
            "GCSC_3rd_Customer_Update",
            "Closed_Date",
            "Submit_Date",
            "LastResolvedDate",
            "ReportedDate",
            "RespondedDate",
            "LastModifiedDate",
        ],
        "integer_fields": [
            "Initial_Response_Time",
            "Second_Response_Time",
            "Third_Response_Time",
            "TrueMTTR_mins",
        ],
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
            "Incident_Number",
            "WorkLog_Type",
            "WorkLog_ID",
            "WorkLog_Submit_Date",
            "WorkLog_Submitter",
            "Last_Modified_Date",
            "Last_Modified_By",
            "ExtractedDescription",
        ],
        "field_map": {
            "IncidentNumber": "Incident_Number",
            "WorkLogType": "WorkLog_Type",
            "WorkLogID": "WorkLog_ID",
            "WorkLogSubmitDate": "WorkLog_Submit_Date",
            "WorkLogSubmitter": "WorkLog_Submitter",
            "LastModifiedDate": "Last_Modified_Date",
            "LastModifiedBy": "Last_Modified_By",
            "ExtractedDescription": "ExtractedDescription",
        },
        "timestamp_fields": ["WorkLog_Submit_Date", "Last_Modified_Date"],
        "integer_fields": [],
    },
]


def load_oauth_credentials():
    """Load OAuth credentials from Secret Manager"""
    max_attempts = 4
    delay_seconds = 1.0

    for attempt in range(1, max_attempts + 1):
        try:
            client = secretmanager.SecretManagerServiceClient()
            secret_name = (
                f"projects/{PROJECT_ID}/secrets/gmail-oauth-token/versions/latest"
            )
            response = client.access_secret_version(request={"name": secret_name})
            token_json = response.payload.data.decode("UTF-8")
            token_data = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(token_data)
            return creds
        except Exception as e:
            if attempt == max_attempts:
                logger.error(f"Failed to load OAuth credentials: {e}")
                raise
            logger.warning(
                "Failed to load OAuth credentials (attempt %s/%s): %s. Retrying in %.1fs.",
                attempt,
                max_attempts,
                e,
                delay_seconds,
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 8.0)


def get_gmail_service():
    """Get Gmail API service"""
    creds = load_oauth_credentials()
    return build("gmail", "v1", credentials=creds)


def get_message_attachment(
    service, message_id: str, attachment_filename: str
) -> Optional[bytes]:
    """Get attachment from Gmail message"""
    try:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        for part in message["payload"].get("parts", []):
            if part["filename"] == attachment_filename:
                if "data" in part["body"]:
                    return base64.urlsafe_b64decode(part["body"]["data"])
                else:
                    attachment_id = part["body"].get("attachmentId")
                    if attachment_id:
                        attachment = (
                            service.users()
                            .messages()
                            .attachments()
                            .get(userId="me", messageId=message_id, id=attachment_id)
                            .execute()
                        )
                        return base64.urlsafe_b64decode(attachment["data"])
        return None
    except Exception as e:
        logger.error(
            f"Failed to get attachment {attachment_filename} from message {message_id}: {e}"
        )
        return None


def get_table_columns(
    bq_client: bigquery.Client, dataset_id: str, table_id: str
) -> List[str]:
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
    clean_message_id = re.sub(r"[^a-zA-Z0-9_]", "_", message_id)[-24:]
    if not clean_message_id:
        clean_message_id = os.urandom(4).hex()
    table_name = f"{config['staging_table']}_run_{run_suffix}_{clean_message_id}"
    return f"{PROJECT_ID}.{config['staging_dataset']}.{table_name}"


def set_temp_table_expiration(
    bq_client: bigquery.Client, table_ref: str, hours: int = 24
) -> None:
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
        target_table_ref = (
            f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
        )
        target_table = bq_client.get_table(target_table_ref)
        existing_columns = [field.name for field in target_table.schema]

        # Case-insensitive column comparison
        existing_columns_lower = {col.lower() for col in existing_columns}
        missing_columns = [
            col for col in staging_columns if col.lower() not in existing_columns_lower
        ]

        if not missing_columns:
            logger.info("Target table already has all columns.")
            return

        logger.info(
            f"Found {len(missing_columns)} new columns to add: {', '.join(missing_columns)}"
        )

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
                    logger.info(
                        f"Field {col_name} already exists in target (case-insensitive match), skipping."
                    )
                    continue

                # Create new schema with just this one field added
                new_schema = list(target_table.schema)
                staging_field = staging_fields.get(col_name)
                if staging_field:
                    new_field = bigquery.SchemaField(
                        name=col_name,
                        field_type=staging_field.field_type,
                        mode="NULLABLE",
                    )
                else:
                    new_field = bigquery.SchemaField(
                        name=col_name, field_type="STRING", mode="NULLABLE"
                    )
                new_schema.append(new_field)

                target_table.schema = new_schema
                bq_client.update_table(target_table, ["schema"])
                logger.info(f"Successfully added field {col_name} to target table.")
                fields_added += 1

            except Exception as field_error:
                # If the error is about a field already existing, continue (it was added by another process)
                if "already exists" in str(field_error):
                    logger.info(
                        f"Field {col_name} already exists (concurrent update): {field_error}. Continuing."
                    )
                    fields_added += 1  # Count as successful since field exists
                else:
                    logger.error(f"Failed to add field {col_name}: {field_error}")
                    fields_failed.append(col_name)
                    # Continue to attempt adding remaining fields

        logger.info(
            f"Field addition complete: {fields_added} fields successfully added or confirmed, {len(fields_failed)} failures."
        )
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


def manage_gmail_labels(
    service,
    message_id: str,
    remove_label_name: str,
    add_label_name: str,
    extra_remove_label_name: Optional[str] = None,
):
    """Remove and add labels to Gmail message, and mark as read"""
    try:
        # Get all labels
        labels_result = service.users().labels().list(userId="me").execute()
        labels = {
            label["name"]: label["id"] for label in labels_result.get("labels", [])
        }

        remove_label_id = labels.get(remove_label_name)
        add_label_id = labels.get(add_label_name)
        unread_label_id = labels.get("UNREAD")

        # Prepare modifications: remove label, add label, and mark as read
        modifications = {}
        remove_ids = []
        add_ids = []

        if remove_label_id:
            remove_ids.append(remove_label_id)

        if extra_remove_label_name:
            extra_remove_label_id = labels.get(extra_remove_label_name)
            if extra_remove_label_id:
                remove_ids.append(extra_remove_label_id)

        if unread_label_id:
            remove_ids.append(unread_label_id)

        if add_label_id:
            add_ids.append(add_label_id)

        # Apply all modifications in one call
        if remove_ids or add_ids:
            if remove_ids:
                modifications["removeLabelIds"] = remove_ids
            if add_ids:
                modifications["addLabelIds"] = add_ids

            service.users().messages().modify(
                userId="me", id=message_id, body=modifications
            ).execute()
            logger.info(
                f"Modified message {message_id}: removed labels {remove_ids}, added labels {add_ids}"
            )

    except Exception as e:
        logger.error(f"Failed to manage labels for message {message_id}: {e}")
        raise


RFC822_HEADER_RE = re.compile(
    r"^(date|from|to|cc|bcc|subject|sent|reply-to|mime-version|content-type"
    r"|content-transfer-encoding|message-id|delivered-to|x-mailer)\s*:",
    re.IGNORECASE,
)


def sanitize_csv_text(text: str) -> Tuple[str, int]:
    """Strip forwarded-email preamble lines that precede the CSV header row.

    BMC exports intermittently arrive wrapped in a forwarded-email body:
    separator rules ('====', '++++'), RFC-822 headers ('Date: ...'), and blank
    lines ahead of the real CSV header. Those lines parse as 1-3 column rows and
    trip the row-width guard, failing the whole run.

    Only *leading* junk is removed here. Anything interleaved with the data rows
    is filtered after parsing (see is_non_data_artifact_row), where csv quoting
    has already been resolved -- a line-based quote-parity heuristic gets this
    wrong whenever a description contains a stray quote character, and it would
    then corrupt legitimately quoted multi-line fields.
    """
    lines = text.splitlines()
    removed = 0
    while lines:
        stripped = lines[0].strip()
        if (
            stripped
            and re.search(r"[A-Za-z0-9]", stripped)
            and not RFC822_HEADER_RE.match(stripped)
        ):
            break
        lines.pop(0)
        removed += 1
    return "\n".join(lines), removed


def is_non_data_artifact_row(row: List[str]) -> bool:
    """True when a parsed row is forwarded-email junk rather than CSV data.

    Artifacts observed in production are RFC-822 header lines ('To: ...',
    'Date: ...'), separator rules ('====', '++++') and blank filler lines. A real
    data row always begins with a ticket/worklog identifier, so it can never be
    mistaken for an RFC-822 header, and a separator/blank row carries no
    alphanumeric content. Evaluated after parsing so that newlines belonging to a
    quoted multi-line field are never considered (they are not rows at all).
    """
    cells = [(cell or "").strip() for cell in row]
    if not any(cells):
        return True
    if len(row) == 1 and not re.search(r"[A-Za-z0-9]", cells[0]):
        return True
    return RFC822_HEADER_RE.match(cells[0]) is not None


def robust_parse_csv(csv_data: bytes) -> List[List[str]]:
    """Parse CSV with multiple encoding attempts"""
    encodings = ["utf-8", "utf-16", "latin-1", "cp1252"]
    candidates: List[List[List[str]]] = []
    junk_removed_counts: List[int] = []

    def try_parse(
        text: str, delimiter: str, quote_none: bool = False
    ) -> Optional[List[List[str]]]:
        reader_kwargs = {"delimiter": delimiter}
        if quote_none:
            reader_kwargs.update({"quoting": csv.QUOTE_NONE, "escapechar": "\\"})
        reader = csv.reader(io.StringIO(text), **reader_kwargs)
        rows = list(reader)
        if len(rows) < 2:
            return None

        # Leading wrapper lines the sanitizer cannot classify (e.g. 'Hi GSOC:'
        # carries alphanumerics and is not an RFC-822 header) would otherwise make
        # the structural check below reject an otherwise valid payload. Find the
        # widest of the first rows and drop what precedes it -- but only when
        # everything before it is single-cell filler, so a data row that is wider
        # than the header is never allowed to push the header out of the payload.
        probe_limit = min(len(rows), 10)
        widest_index = 0
        for index in range(probe_limit):
            if len(rows[index]) > len(rows[widest_index]):
                widest_index = index
        if len(rows[widest_index]) <= 1:
            return None
        if widest_index and all(len(rows[i]) <= 1 for i in range(widest_index)):
            rows = rows[widest_index:]
        if not any(cell.strip() for cell in rows[0]):
            return None
        return rows

    for encoding in encodings:
        try:
            text = csv_data.decode(encoding)
            text = text.lstrip("\ufeff")  # Remove BOM
            text, junk_removed = sanitize_csv_text(text)
            junk_removed_counts.append(junk_removed)

            sample = text[:4096]
            sniffer_delimiter = None
            try:
                sniffer_delimiter = (
                    csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"]).delimiter
                )
            except Exception:
                sniffer_delimiter = None

            parse_order = []
            if sniffer_delimiter:
                parse_order.append((sniffer_delimiter, False))
            parse_order.extend(
                [
                    (",", False),
                    (";", False),
                    ("\t", False),
                    (",", True),
                    (";", True),
                    ("\t", True),
                ]
            )

            seen_strategies = set()
            for delimiter, quote_none in parse_order:
                strategy_key = (delimiter, quote_none)
                if strategy_key in seen_strategies:
                    continue
                seen_strategies.add(strategy_key)
                try:
                    rows = try_parse(text, delimiter, quote_none)
                    if rows:
                        candidates.append(rows)
                except Exception:
                    continue
        except Exception:
            continue

    if candidates:
        # Prefer the parse with the widest header, which is usually the correct delimiter.
        candidates.sort(key=lambda candidate: len(candidate[0]), reverse=True)
        return candidates[0]

    raise ValueError("Could not parse CSV with any encoding/delimiter combination")


def detect_known_non_data_payload(csv_data: bytes) -> Optional[str]:
    """Detect known Remedy outage/maintenance payloads mislabeled as CSV attachments."""
    try:
        preview_text = csv_data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None

    if not preview_text:
        return None

    preview_lower = preview_text.lower()
    maintenance_terms = [
        "maintenance",
        "under maintenance",
        "service unavailable",
        "temporarily unavailable",
    ]
    server_error_terms = [
        "internal server error",
        "server error",
    ]

    # Guard against false positives: valid exports are tabular (header + rows).
    # Non-data maintenance payloads are expected to be single-row bodies.
    lines = [line for line in preview_text.splitlines() if line.strip()]
    if len(lines) > 1:
        return None

    try:
        payload = json.loads(preview_text)
        if isinstance(payload, dict):
            status_code = payload.get("statusCode")
            status_code_int = None
            try:
                status_code_int = int(status_code) if status_code is not None else None
            except Exception:
                status_code_int = None

            combined_text = " ".join(
                [
                    str(payload.get("error", "")),
                    str(payload.get("message", "")),
                ]
            ).lower()

            if status_code_int is not None and status_code_int >= 500:
                return f"upstream_http_{status_code_int}"

            if any(term in combined_text for term in maintenance_terms):
                return "upstream_maintenance_payload"

            if any(term in combined_text for term in server_error_terms):
                return "upstream_server_error_payload"
    except Exception:
        # Non-JSON payloads can still contain recognizable outage text.
        pass

    # For plain-text single-row bodies, classify known outage phrases.
    if len(lines) == 1:
        if any(term in preview_lower for term in maintenance_terms):
            return "upstream_maintenance_payload"

        if any(term in preview_lower for term in server_error_terms):
            return "upstream_server_error_payload"

    return None


def standardize_field_name(header: str, field_map: Dict[str, str]) -> str:
    """Standardize field name using field map"""
    normalized_header = header.strip().strip('"').strip("'")
    return field_map.get(normalized_header, normalized_header.replace(" ", "_"))


def normalize_customer_name(value: Any) -> Any:
    """Remove leading/trailing quotation marks from customer name."""
    if value is None:
        return None

    cleaned = str(value).strip()
    if cleaned and cleaned[0] == '"' and cleaned[-1] == '"' and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned if cleaned else None


def normalize_text_field(value: Any) -> Any:
    """Strip surrounding quotes and any leftover double-quote chars from free-text fields.

    Unlike ``normalize_rsm_name`` this does NOT reorder comma-separated values, so it is
    safe for free-text fields such as ``Summary``, ``Fault_Location``, ``Service_Type``
    and ``Destination``.
    """
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned:
        return None

    # Strip one level of surrounding quotes (payload artifact from the export).
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in ('"', "'")
    ):
        cleaned = cleaned[1:-1].strip()

    # Cleanup: drop any double-quote chars still left in the value.
    if '"' in cleaned:
        cleaned = cleaned.replace('"', "").strip()

    return cleaned if cleaned else None


def normalize_rsm_name(value: Any) -> Any:
    """Convert surname-first comma-delimited RSM values into display order."""
    if value is None:
        return None

    cleaned = str(value).strip().strip('"').strip("'")
    if not cleaned:
        return None

    parts = [part.strip() for part in cleaned.split(",") if part and part.strip()]
    if len(parts) < 2:
        return cleaned

    return " ".join(parts[1:] + [parts[0]])


def handle_empty_values(value: Any, is_timestamp: bool, is_integer: bool) -> Any:
    """Handle empty values and type conversions"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    value_str = str(value).strip()

    # Strip one level of surrounding quotes (payload artifact from the export).
    if (
        len(value_str) >= 2
        and value_str[0] == value_str[-1]
        and value_str[0] in ('"', "'")
    ):
        value_str = value_str[1:-1].strip()

    if is_timestamp:
        # Try multiple timestamp formats
        patterns = [
            (r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$", "{3}-{1}-{0}T{3}:{4}:00"),
            (
                r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$",
                "{0}-{1}-{2}T{3}:{4}:{5}",
            ),
            (r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$", "{0}-{1}-{2}T{3}:{4}:00"),
        ]

        for pattern, template in patterns:
            match = re.match(pattern, value_str)
            if match:
                groups = match.groups()
                try:
                    # Simple validation
                    datetime.strptime(template.format(*groups), "%Y-%m-%dT%H:%M:%S")
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


def locate_header_row(rows: List[List[str]], config: Dict[str, Any]) -> int:
    """Return the index of the row holding the CSV header.

    Normally this is row 0, but forwarded-email wrapper content can precede the
    real header, so the rows are scanned forward for the first one that satisfies
    the header contract. Raises ValueError when no row does -- which is what
    catches a genuine format change (e.g. a different delimiter) instead of
    silently merging a fraction of the file.
    """
    expected_headers = list(config["all_columns"])
    headers: List[str] = []
    for index, row in enumerate(rows):
        headers = [standardize_field_name(h, config["field_map"]) for h in row]
        if all(column in headers for column in expected_headers):
            return index
    missing_headers = [column for column in expected_headers if column not in headers]
    raise ValueError(
        f"Header contract violation for {config['name']}: missing required "
        f"headers {missing_headers}. Got: {headers}"
    )


def process_csv_attachment(
    service, message_id: str, attachment_filename: str, config: Dict[str, Any]
) -> Tuple[bool, int, Optional[str]]:
    """Process a single CSV attachment"""
    logger.info(
        f"Processing attachment: {attachment_filename} for config: {config['name']}"
    )

    # Get attachment data
    csv_data = get_message_attachment(service, message_id, attachment_filename)
    if not csv_data:
        logger.warning(f"Could not retrieve attachment {attachment_filename}")
        return False, 0, None

    non_data_reason = detect_known_non_data_payload(csv_data)
    if non_data_reason:
        logger.warning(
            "Skipping attachment %s due to known non-data payload (%s)",
            attachment_filename,
            non_data_reason,
        )
        return True, 0, non_data_reason

    bq_client = get_bq_client()
    staging_table_id = build_run_scoped_staging_table_id(config, message_id)

    try:
        # Parse CSV
        rows = robust_parse_csv(csv_data)

        # ---- Locate the header row and enforce the header contract. Normally this
        # ---- is rows[0]; forwarded-email wrapper content can precede it, so the
        # ---- rows are scanned forward for the first row that satisfies the contract.
        header_index = locate_header_row(rows, config)
        headers = [
            standardize_field_name(header, config["field_map"])
            for header in rows[header_index]
        ]
        if header_index:
            logger.warning(
                "Skipped %s non-header line(s) before the header row in %s",
                header_index,
                attachment_filename,
            )

        data_rows = max(len(rows) - header_index - 1, 0)
        if data_rows < MIN_VALID_CSV_DATA_ROWS:
            logger.warning(
                "Skipping attachment %s due to insufficient data rows (%s < %s)",
                attachment_filename,
                data_rows,
                MIN_VALID_CSV_DATA_ROWS,
            )
            return True, 0, "insufficient_csv_rows"

        ndjson_lines = []

        junk_rows_skipped = 0
        ragged_rows_skipped = 0
        over_width_rows_skipped = 0
        ragged_row_samples: List[List[str]] = []

        for row in rows[header_index + 1 :]:
            # ---- Non-data artifact rows: forwarded-email junk interleaved in the
            # ---- export (e.g. 'To: ...', 'Date: ...', '===='). These are dropped
            # ---- rather than failing the run. Classified post-parse, so newlines
            # ---- inside quoted multi-line fields are never touched.
            if is_non_data_artifact_row(row):
                junk_rows_skipped += 1
                continue

            # ---- A real data row must match the header width. Narrower rows are
            # ---- stray wrapper text ('Hi GSOC:', 'To: ...'), so they are dropped
            # ---- with a warning; wider rows mean the payload itself is broken
            # ---- (e.g. a delimiter leaking out of an unquoted field) and are
            # ---- rate-limited below so a genuine data problem still fails loudly.
            if len(row) != len(headers):
                ragged_rows_skipped += 1
                if len(row) > len(headers):
                    over_width_rows_skipped += 1
                if len(ragged_row_samples) < 3:
                    ragged_row_samples.append(row[:5])
                continue
            obj = {}
            for i, header in enumerate(headers):
                value = row[i] if i < len(row) else None
                is_ts = header in config["timestamp_fields"]
                is_int = header in config["integer_fields"]
                normalized_value = handle_empty_values(value, is_ts, is_int)
                if header == "RSMName":
                    normalized_value = normalize_rsm_name(normalized_value)
                if header in [
                    "Summary",
                    "Fault_Location",
                    "Service_Type",
                    "Destination",
                ]:
                    normalized_value = normalize_text_field(normalized_value)
                if header == "Customer_Name":
                    normalized_value = normalize_customer_name(normalized_value)
                obj[header] = normalized_value
            ndjson_lines.append(json.dumps(obj))

        if junk_rows_skipped:
            logger.warning(
                "Skipped %s non-CSV artifact row(s) in %s (forwarded-email junk interleaved in export)",
                junk_rows_skipped,
                attachment_filename,
            )

        # ---- Guardrails: the export is known to interleave forwarded-email wrapper
        # ---- text, so stray rows are dropped with a warning rather than failing
        # ---- the run. Over-wide rows (extra delimiters) are the real
        # ---- data-integrity signal (a shifted/broken payload), so they are
        # ---- rate-limited and still raise once they dominate the attachment.
        usable_rows = len(ndjson_lines)
        if ragged_rows_skipped:
            logger.warning(
                "Skipped %s row(s) with unexpected column count in %s (%s over-width). "
                "Samples: %s",
                ragged_rows_skipped,
                attachment_filename,
                over_width_rows_skipped,
                ragged_row_samples,
            )
            candidate_rows = ragged_rows_skipped + usable_rows
            if (
                over_width_rows_skipped
                and candidate_rows
                and over_width_rows_skipped / candidate_rows > MAX_RAGGED_ROW_RATIO
            ):
                raise ValueError(
                    f"Row width mismatch in {config['name']}: "
                    f"{over_width_rows_skipped} of {candidate_rows} candidate rows had "
                    f"more than the expected {len(headers)} columns. "
                    f"Samples: {ragged_row_samples}"
                )

        if not usable_rows:
            logger.warning(
                "Skipping attachment %s: no usable data rows after dropping %s "
                "artifact row(s) and %s malformed row(s)",
                attachment_filename,
                junk_rows_skipped,
                ragged_rows_skipped,
            )
            return True, 0, "no_usable_rows"

        ndjson_content = "\n".join(ndjson_lines)

        # Load to run-scoped staging table to avoid concurrent run collisions.
        # Enforce schema types to stop autodetect from drifting timestamp fields to STRING.
        schema_type_map = {col: "STRING" for col in config["all_columns"]}
        for ts_col in config["timestamp_fields"]:
            schema_type_map[ts_col] = "TIMESTAMP"
        for int_col in config["integer_fields"]:
            schema_type_map[int_col] = "INT64"

        schema_fields = [
            bigquery.SchemaField(
                name=col,
                field_type=schema_type_map.get(col, "STRING"),
                mode="NULLABLE",
            )
            for col in config["all_columns"]
        ]

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=False,
            schema=schema_fields,
        )

        load_job = bq_client.load_table_from_file(
            io.BytesIO(ndjson_content.encode()), staging_table_id, job_config=job_config
        )
        load_job.result()
        logger.info(f"Loaded data to {staging_table_id}")
        set_temp_table_expiration(bq_client, staging_table_id)

        # Get actual columns from staging table after load (dynamic column detection)
        staging_columns = get_table_columns_by_ref(bq_client, staging_table_id)
        logger.info(f"Detected {len(staging_columns)} columns in staging table.")

        # Ensure target table has all columns from staging
        ensure_target_table_columns(
            bq_client, config, staging_columns, staging_table_id
        )

        # Merge into target table using dynamic staging columns with case-insensitive matching
        target_table_id = (
            f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
        )
        target_columns = get_table_columns(
            bq_client, config["target_dataset"], config["target_table"]
        )
        primary_key = config["primary_key"]

        logger.info(
            f"Staging table has {len(staging_columns)} columns, target table has {len(target_columns)} columns."
        )

        # Build a case-insensitive map of target columns for matching
        target_columns_lower = {col.lower(): col for col in target_columns}

        # Get all staging columns, using the actual target column name if it exists (case-insensitive)
        merge_columns = []
        for col in staging_columns:
            if col.lower() in target_columns_lower:
                merge_columns.append(
                    target_columns_lower[col.lower()]
                )  # Use the actual target column name

        if len(merge_columns) < len(staging_columns):
            missing = [
                col
                for col in staging_columns
                if col.lower() not in target_columns_lower
            ]
            logger.warning(
                f"Warning: {len(missing)} staging columns not in target: {', '.join(missing)}"
            )
            logger.info(
                f"Will merge {len(merge_columns)} columns that exist in both tables."
            )

        duplicate_check_query = f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT {primary_key}) AS distinct_keys
        FROM `{staging_table_id}`
        WHERE {primary_key} IS NOT NULL
        """
        duplicate_check_job = bq_client.query(
            duplicate_check_query,
            job_config=bigquery.QueryJobConfig(use_legacy_sql=False),
        )
        duplicate_check_row = next(iter(duplicate_check_job.result()), None)
        if duplicate_check_row:
            total_rows = int(duplicate_check_row.total_rows or 0)
            distinct_keys = int(duplicate_check_row.distinct_keys or 0)
            duplicate_rows = max(total_rows - distinct_keys, 0)
            if duplicate_rows > 0:
                logger.warning(
                    "Detected %s duplicate source row(s) on primary key %s in %s. Applying pre-merge deduplication.",
                    duplicate_rows,
                    primary_key,
                    config["name"],
                )

        dedupe_order_col = next(
            (c for c in config["timestamp_fields"] if c in merge_columns), None
        )
        dedupe_order_expr = (
            f"H.{dedupe_order_col} DESC" if dedupe_order_col else f"H.{primary_key}"
        )

        deduped_source_query = f"""
        SELECT * EXCEPT(_rn)
        FROM (
            SELECT
                H.*,
                ROW_NUMBER() OVER (
                    PARTITION BY H.{primary_key}
                    ORDER BY {dedupe_order_expr}
                ) AS _rn
            FROM `{staging_table_id}` H
            WHERE H.{primary_key} IS NOT NULL
        )
        WHERE _rn = 1
        """

        # Aggregate related-item rows into arrays per primary key so the
        # single target row per incident keeps every related item.
        array_cols = [c for c in ARRAY_COLUMNS if c in merge_columns]
        if array_cols:
            except_list = ", ".join(array_cols)
            agg_selects = ", ".join(
                f"ARRAY_AGG(NULLIF(s.{c}, '') IGNORE NULLS ORDER BY NULLIF(s.{c}, '')) AS {c}"
                for c in array_cols
            )
            array_selects = ", ".join(f"A.{c} AS {c}" for c in array_cols)
            deduped_source_query = f"""
            SELECT d.* EXCEPT({except_list}), {array_selects}
            FROM (
                {deduped_source_query}
            ) d
            LEFT JOIN (
                SELECT {primary_key} AS _array_pk, {agg_selects}
                FROM `{staging_table_id}` AS s
                WHERE s.{primary_key} IS NOT NULL
                GROUP BY s.{primary_key}
            ) A ON d.{primary_key} = A._array_pk
            """
            logger.info(
                "Aggregating %s into ARRAY columns at merge time.", ", ".join(array_cols)
            )

        # Build merge query with dynamic columns from staging.
        # Staging types are autodetected from NDJSON and can occasionally drift
        # to STRING for date/time fields; cast defensively at merge time.
        def source_expr(col: str) -> str:
            if col in config["timestamp_fields"]:
                return f"SAFE_CAST(H.{col} AS TIMESTAMP)"
            if col in config["integer_fields"]:
                return f"SAFE_CAST(H.{col} AS INT64)"
            return f"H.{col}"

        # Prevent stale snapshots from overwriting newer target rows.
        freshness_candidates = [
            "LastModifiedDate",
            "Last_Modified_Date",
            "Submit_Date",
            "WorkLog_Submit_Date",
        ]
        freshness_col = next(
            (
                c
                for c in freshness_candidates
                if c in merge_columns and c in target_columns
            ),
            None,
        )
        update_match_condition = "TRUE"
        if freshness_col:
            update_match_condition = (
                f"(H.{freshness_col} IS NOT NULL AND "
                f"(T.{freshness_col} IS NULL OR H.{freshness_col} >= T.{freshness_col}))"
            )
            logger.info(
                "Applying recency guard on %s to avoid stale overwrite in %s.",
                freshness_col,
                config["name"],
            )
        else:
            logger.warning(
                "No freshness column found for %s. Falling back to unconditional updates.",
                config["name"],
            )

        update_cols = [col for col in merge_columns if col != primary_key]
        update_set = ",".join([f"T.{col} = {source_expr(col)}" for col in update_cols])
        insert_cols = ",".join(merge_columns)
        insert_vals = ",".join([source_expr(col) for col in merge_columns])

        merge_query = f"""
        MERGE `{target_table_id}` T
        USING (
            {deduped_source_query}
        ) H
        ON T.{primary_key} = H.{primary_key}
        WHEN MATCHED AND {update_match_condition} THEN
            UPDATE SET {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols}) VALUES ({insert_vals})
        """

        logger.info(
            f"Using {len(merge_columns)} columns from staging for merge into {target_table_id}."
        )

        query_config = bigquery.QueryJobConfig(use_legacy_sql=False)

        merge_job = None
        max_merge_attempts = 8
        merge_delay_seconds = 1.0
        for attempt in range(1, max_merge_attempts + 1):
            try:
                merge_job = bq_client.query(merge_query, job_config=query_config)
                merge_job.result()
                break
            except BadRequest as merge_error:
                err_text = str(merge_error).lower()
                retryable_conflict = (
                    "could not serialize access" in err_text
                    or "concurrent update" in err_text
                    or "aborted due to concurrent update" in err_text
                    or "resources exceeded" in err_text
                    or "too many dml statements outstanding" in err_text
                )
                if not retryable_conflict or attempt == max_merge_attempts:
                    raise

                logger.warning(
                    "Retryable merge/write contention on %s (%s/%s): %s. Retrying in %.1fs.",
                    config["name"],
                    attempt,
                    max_merge_attempts,
                    merge_error,
                    merge_delay_seconds,
                )
                time.sleep(merge_delay_seconds)
                merge_delay_seconds = min(merge_delay_seconds * 2, 12.0)

        source_keys, target_keys, missing_keys, missing_sample = (
            reconcile_merged_primary_keys(
                bq_client,
                primary_key,
                staging_table_id,
                target_table_id,
            )
        )
        logger.info(
            "Reconciliation for %s: source_keys=%s target_keys=%s missing=%s",
            config["name"],
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
        logger.info(
            f"Merged data into {target_table_id}. Rows affected: {rows_affected}"
        )

        return True, int(rows_affected), None

    except Exception as e:
        error_text = str(e).lower()
        non_retryable_reasons = {
            "could not parse csv with any encoding/delimiter combination": "unparseable_csv_payload",
        }
        for marker, reason in non_retryable_reasons.items():
            if marker in error_text:
                logger.warning(
                    "Skipping attachment %s due to non-retryable parse issue (%s): %s",
                    attachment_filename,
                    reason,
                    e,
                )
                return True, 0, reason

        logger.error(f"Error processing CSV {attachment_filename}: {e}")
        return False, 0, None
    finally:
        try:
            bq_client.delete_table(staging_table_id, not_found_ok=True)
            logger.info(f"Deleted run-scoped staging table {staging_table_id}")
        except NotFound:
            pass
        except Exception as cleanup_error:
            logger.warning(
                f"Failed to delete staging table {staging_table_id}: {cleanup_error}"
            )


def log_pipeline_run(
    run_id: str,
    status: str,
    log_level: str,
    message: str,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    rows_merged: Optional[int] = None,
    error_code: Optional[str] = None,
    context_obj: Optional[Dict] = None,
):
    """Log pipeline run to BigQuery using MERGE (identical to GAS script)"""
    try:
        duration_seconds = None
        if (status in ("SUCCESS", "ERROR")) and _script_start_time:
            duration_seconds = (datetime.utcnow() - _script_start_time).total_seconds()

        context_json = json.dumps(context_obj) if context_obj is not None else None

        # Build MERGE query matching GAS script behavior while preserving optional context payload.
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
                SAFE.PARSE_JSON(@ctx) AS Context
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
                bigquery.ScalarQueryParameter("ctx", "STRING", context_json),
            ]
        )

        bq_client = get_bq_client()
        logger.info(f"Logging pipeline run: {status} - {message} (RunID: {run_id})")

        max_attempts = 8
        delay_seconds = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                query_job = bq_client.query(merge_query, job_config=job_config)
                query_job.result(timeout=45)
                logger.info(
                    f"Pipeline run logged successfully. Job ID: {query_job.job_id}"
                )
                return
            except Exception as attempt_error:
                err_text = str(attempt_error).lower()
                retryable_logging_error = (
                    "resources exceeded" in err_text
                    or "too many dml statements outstanding" in err_text
                    or "could not serialize access" in err_text
                    or "concurrent update" in err_text
                )
                if not retryable_logging_error:
                    raise
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
                delay_seconds = min(delay_seconds * 2, 12.0)

    except Exception as e:
        logger.warning(f"logPipelineRun failed: {e}")
        logger.warning(f"Stack trace: {str(e)}")


def cleanup_stale_running() -> None:
    """Mark stale RUNNING rows for this pipeline as ERROR (timeout or crash).

    RUNNING rows older than 1 hour can only be orphans from a killed
    invocation; real runs finish in minutes. Runs once per invocation.
    """
    try:
        cleanup_query = f"""
            UPDATE `{PROJECT_ID}.{DATASET_ID}.{PIPELINE_RUNS_TABLE}`
            SET Status = 'ERROR',
                Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = @pipeline
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("pipeline", "STRING", SCRIPT_NAME)
            ]
        )
        bq_client = get_bq_client()
        bq_client.query(cleanup_query, job_config=job_config).result(timeout=45)
        logger.info("Stale RUNNING cleanup completed")
    except Exception as cleanup_error:
        logger.warning(f"Stale RUNNING cleanup failed: {cleanup_error}")


@functions_framework.cloud_event
def process_bq_hdwl_email(cloud_event):
    """Main Cloud Function entry point"""
    global _script_start_time, _current_run_id

    _current_run_id = os.urandom(16).hex()
    _script_start_time = datetime.utcnow()

    logger.info(f"Starting pipeline run {_current_run_id}")
    cleanup_stale_running()
    log_pipeline_run(
        _current_run_id,
        "RUNNING",
        "INFO",
        "Pipeline run started",
        None,
        None,
        None,
        None,
        None,
    )

    try:
        # Decode Pub/Sub message
        pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode()
        try:
            message_data = json.loads(pubsub_message)
        except json.JSONDecodeError:
            # Some manual publishers emit single-quoted or otherwise malformed dict payloads.
            try:
                parsed = ast.literal_eval(pubsub_message)
                if not isinstance(parsed, dict):
                    raise ValueError("Decoded Pub/Sub payload is not an object")
                message_data = parsed
            except Exception:
                # Last-resort compatibility: extract messageId token from loosely formatted payloads.
                msg_id_match = re.search(
                    r"messageId\s*[:=]\s*['\"]?([A-Za-z0-9]+)", pubsub_message
                )
                if not msg_id_match:
                    raise ValueError(
                        f"Unable to parse Pub/Sub payload: {pubsub_message[:200]}"
                    )
                message_data = {"messageId": msg_id_match.group(1)}

        message_id = message_data.get("messageId")
        if not message_id or str(message_id).upper() == "PLACEHOLDER":
            skip_message = f"Skipping run due to invalid messageId: {message_id}"
            logger.warning(skip_message)
            log_pipeline_run(
                _current_run_id,
                "SUCCESS",
                "WARNING",
                skip_message,
                None,
                None,
                0,
                None,
                {"messageId": message_id, "skipped": True},
            )
            return

        logger.info(f"Processing email message: {message_id}")

        service = get_gmail_service()
        total_rows_merged = 0
        failed_attachments = []
        unmatched_csv_attachments = []
        skipped_attachments = []
        matched_config_names = set()
        expected_config_names = {cfg["name"] for cfg in CSV_CONFIGURATIONS}
        rows_by_config = {cfg["name"]: 0 for cfg in CSV_CONFIGURATIONS}

        # Get message to find attachments
        try:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as gmail_error:
            if "Invalid id value" in str(gmail_error):
                skip_message = (
                    f"Skipping run due to Gmail invalid messageId: {message_id}"
                )
                logger.warning(skip_message)
                log_pipeline_run(
                    _current_run_id,
                    "SUCCESS",
                    "WARNING",
                    skip_message,
                    None,
                    None,
                    0,
                    None,
                    {
                        "messageId": message_id,
                        "skipped": True,
                        "reason": "invalidMessageId",
                    },
                )
                return
            raise
        logger.info(
            f"Message retrieved. Payload parts count: {len(message['payload'].get('parts', []))}"
        )

        # Process each CSV attachment
        csv_found = False
        for part in message["payload"].get("parts", []):
            filename = part.get("filename", "").lower()
            logger.info(f"Checking part: filename='{filename}'")
            if filename.endswith(".csv"):
                csv_found = True
                logger.info(f"Found CSV attachment: {filename}")
                # Find matching config
                matched_config = False
                for config in CSV_CONFIGURATIONS:
                    if filename.startswith(config["filename_prefix"]):
                        matched_config = True
                        matched_config_names.add(config["name"])
                        logger.info(f"Matched config: {config['name']}")
                        success, rows, skip_reason = process_csv_attachment(
                            service, message_id, part["filename"], config
                        )
                        logger.info(
                            f"CSV processing result: success={success}, rows={rows}, skip_reason={skip_reason}"
                        )
                        if success:
                            total_rows_merged += rows
                            rows_by_config[config["name"]] += rows
                            if skip_reason:
                                skipped_attachments.append(
                                    {"filename": filename, "reason": skip_reason}
                                )
                        else:
                            failed_attachments.append(filename)
                        break
                if not matched_config:
                    logger.warning(f"No matching config for CSV attachment: {filename}")
                    unmatched_csv_attachments.append(filename)

        if not csv_found:
            raise RuntimeError("No CSV attachments found in message")

        missing_expected_configs = sorted(expected_config_names - matched_config_names)
        if missing_expected_configs:
            raise RuntimeError(
                "Missing expected CSV attachment(s): "
                f"{missing_expected_configs}. Matched={sorted(matched_config_names)}"
            )

        if failed_attachments or unmatched_csv_attachments:
            raise RuntimeError(
                "Attachment processing incomplete. "
                f"Failed: {failed_attachments}; Unmatched: {unmatched_csv_attachments}"
            )

        # Manage labels: remove 'pubsub', add 'ArchivedReports'
        manage_gmail_labels(
            service,
            message_id,
            "pubsub",
            "ArchivedReports",
            extra_remove_label_name="HDWL_PROCESSING",
        )

        success_message = (
            "Pipeline finished. "
            f"RowsMergedTotal={total_rows_merged}; "
            f"RowsByTable={rows_by_config}; "
            f"MatchedConfigs={sorted(matched_config_names)}; "
            f"SkippedAttachments={len(skipped_attachments)}"
        )
        success_log_level = "WARNING" if skipped_attachments else "INFO"
        success_error_code = "UPSTREAM_MAINTENANCE" if skipped_attachments else None
        log_pipeline_run(
            _current_run_id,
            "SUCCESS",
            success_log_level,
            success_message,
            None,
            None,
            total_rows_merged,
            success_error_code,
            {
                "messageId": message_id,
                "rowsByTable": rows_by_config,
                "matchedConfigs": sorted(matched_config_names),
                "failedAttachments": failed_attachments,
                "unmatchedCsvAttachments": unmatched_csv_attachments,
                "skippedAttachments": skipped_attachments,
            },
        )
        logger.info(f"Pipeline run {_current_run_id} completed successfully")

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        log_pipeline_run(
            _current_run_id,
            "ERROR",
            "ERROR",
            str(e),
            None,
            None,
            None,
            None,
            {
                "messageId": message_id if "message_id" in locals() else None,
                "failedAttachments": failed_attachments
                if "failed_attachments" in locals()
                else [],
                "unmatchedCsvAttachments": unmatched_csv_attachments
                if "unmatched_csv_attachments" in locals()
                else [],
                "skippedAttachments": skipped_attachments
                if "skipped_attachments" in locals()
                else [],
                "matchedConfigs": sorted(matched_config_names)
                if "matched_config_names" in locals()
                else [],
                "rowsByTable": rows_by_config if "rows_by_config" in locals() else {},
            },
        )
        raise
