"""
Cloud Function to process BQ - BMC User List emails from Gmail via Pub/Sub.
Loads CSV attachment data into BigQuery tables using WRITE_TRUNCATE.
"""

import base64
import ast
import csv
import io
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import functions_framework
from google.cloud import bigquery, secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from logging_config import setup_root_logging

setup_root_logging()
logger = logging.getLogger(__name__)

PROJECT_ID = "pccw-internal-virt-agent-uat"
PIPELINE_DATASET_ID = "GSO"
PIPELINE_RUNS_TABLE = "PipelineRuns"
SCRIPT_NAME = "pubsub - BMC User List"
EXPECTED_SUBJECT = "BQ - BMC User List"

GMAIL_LABEL_TO_REMOVE = "pubsub"
GMAIL_LABEL_TO_ADD = "ArchivedReports"

TARGET_TABLES = [
	"pccw-internal-virtual-agent.BMC.UserList",
	"pccw-internal-virt-agent-uat.BMC.UserList",
]

_script_start_time = None
_current_run_id = None
_bq_client = None


def get_bq_client() -> bigquery.Client:
	"""Reuse one BigQuery client per instance to reduce connection churn."""
	global _bq_client
	if _bq_client is None:
		_bq_client = bigquery.Client(project=PROJECT_ID)
	return _bq_client


def load_oauth_credentials() -> Credentials:
	"""Load Gmail OAuth credentials from Secret Manager."""
	client = secretmanager.SecretManagerServiceClient()
	secret_name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-token/versions/latest"
	response = client.access_secret_version(request={"name": secret_name})
	token_json = response.payload.data.decode("utf-8")
	token_data = json.loads(token_json)
	return Credentials.from_authorized_user_info(token_data)


def get_gmail_service():
	"""Build Gmail API client."""
	creds = load_oauth_credentials()
	return build("gmail", "v1", credentials=creds)


def get_message(service, message_id: str) -> Dict[str, Any]:
	return service.users().messages().get(userId="me", id=message_id, format="full").execute()


def get_message_subject(message: Dict[str, Any]) -> str:
	headers = message.get("payload", {}).get("headers", [])
	for header in headers:
		if header.get("name", "").lower() == "subject":
			return header.get("value", "").strip()
	return ""


def get_message_attachment(service, message_id: str, attachment_filename: str) -> Optional[bytes]:
	"""Get attachment bytes from Gmail message."""
	message = get_message(service, message_id)

	for part in message.get("payload", {}).get("parts", []):
		if part.get("filename") != attachment_filename:
			continue

		body = part.get("body", {})
		if "data" in body:
			return base64.urlsafe_b64decode(body["data"])

		attachment_id = body.get("attachmentId")
		if attachment_id:
			attachment = service.users().messages().attachments().get(
				userId="me", messageId=message_id, id=attachment_id
			).execute()
			return base64.urlsafe_b64decode(attachment["data"])

	return None


def robust_parse_csv(csv_data: bytes) -> List[List[str]]:
	"""Parse CSV content with multiple encoding and delimiter attempts."""
	encodings = ["utf-8", "utf-16", "latin-1", "cp1252"]
	delimiters = [",", ";", "\t"]

	for encoding in encodings:
		try:
			text = csv_data.decode(encoding).lstrip("\ufeff")
		except Exception:
			continue

		for delimiter in delimiters:
			try:
				reader = csv.reader(io.StringIO(text), delimiter=delimiter)
				rows = list(reader)
				if len(rows) > 1 and any(h.strip() for h in rows[0]):
					return rows
			except Exception:
				continue

	raise ValueError("Could not parse CSV with supported encodings and delimiters")


def sanitize_header(header: str) -> str:
	"""Normalize CSV header to a BigQuery-safe column name."""
	candidate = header.strip().replace(" ", "_").replace("-", "_")
	return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in candidate)


def csv_to_records(csv_data: bytes) -> List[Dict[str, Any]]:
	"""Convert CSV bytes to list of JSON-serializable records."""
	rows = robust_parse_csv(csv_data)
	headers = [sanitize_header(h) for h in rows[0]]
	records: List[Dict[str, Any]] = []

	for row in rows[1:]:
		obj: Dict[str, Any] = {}
		for idx, header in enumerate(headers):
			value = row[idx] if idx < len(row) else None
			if value is None:
				obj[header] = None
			else:
				text = str(value).strip()
				obj[header] = text if text else None
		records.append(obj)

	return records


def write_records_to_table(table_ref: str, records: List[Dict[str, Any]]) -> int:
	"""Load records into BigQuery table using WRITE_TRUNCATE."""
	if not records:
		logger.info("No records to write for table %s", table_ref)
		return 0

	headers = list(records[0].keys())
	ndjson_content = "\n".join(json.dumps(r) for r in records)

	job_config = bigquery.LoadJobConfig(
		source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
		write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
		schema=[bigquery.SchemaField(name=h, field_type="STRING") for h in headers],
	)

	bq_client = get_bq_client()
	load_job = bq_client.load_table_from_file(
		io.BytesIO(ndjson_content.encode("utf-8")),
		table_ref,
		job_config=job_config,
	)
	load_job.result()

	table = bq_client.get_table(table_ref)
	row_count = int(table.num_rows or 0)
	logger.info("Loaded %s rows into %s (job_id=%s)", row_count, table_ref, load_job.job_id)
	return row_count


def manage_gmail_labels(service, message_id: str, remove_label_name: str, add_label_name: str):
	"""Remove trigger label, mark read, and add archive label."""
	labels_result = service.users().labels().list(userId="me").execute()
	labels = {label["name"]: label["id"] for label in labels_result.get("labels", [])}

	remove_ids: List[str] = []
	add_ids: List[str] = []

	remove_label_id = labels.get(remove_label_name)
	unread_label_id = labels.get("UNREAD")
	add_label_id = labels.get(add_label_name)

	if remove_label_id:
		remove_ids.append(remove_label_id)
	if unread_label_id:
		remove_ids.append(unread_label_id)
	if add_label_id:
		add_ids.append(add_label_id)

	body: Dict[str, List[str]] = {}
	if remove_ids:
		body["removeLabelIds"] = remove_ids
	if add_ids:
		body["addLabelIds"] = add_ids

	if body:
		service.users().messages().modify(userId="me", id=message_id, body=body).execute()
		logger.info("Updated labels for %s: removed=%s added=%s", message_id, remove_ids, add_ids)


def log_pipeline_run(
	run_id: str,
	status: str,
	log_level: str,
	message: str,
	rows_merged: Optional[int] = None,
	error_code: Optional[str] = None,
):
	"""Log pipeline run to BigQuery via MERGE into GSO.PipelineRuns."""
	try:
		duration_seconds = None
		if status in ("SUCCESS", "ERROR") and _script_start_time:
			duration_seconds = (datetime.utcnow() - _script_start_time).total_seconds()

		merge_query = f"""
		MERGE `{PROJECT_ID}.{PIPELINE_DATASET_ID}.{PIPELINE_RUNS_TABLE}` T
		USING (
			SELECT
				@pipeline AS PipelineName,
				CAST(NULL AS TIMESTAMP) AS WindowStart,
				CAST(NULL AS TIMESTAMP) AS WindowEnd,
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
			T.RowsMerged = COALESCE(S.RowsMerged, T.RowsMerged),
			T.LogLevel = COALESCE(S.LogLevel, T.LogLevel),
			T.Message = COALESCE(S.Message, T.Message),
			T.Status = COALESCE(S.Status, T.Status),
			T.ErrorCode = COALESCE(S.ErrorCode, T.ErrorCode),
			T.DurationSeconds = COALESCE(S.DurationSeconds, T.DurationSeconds),
			T.Context = COALESCE(S.Context, T.Context)
		WHEN NOT MATCHED THEN
			INSERT (
				RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged,
				LogLevel, Message, RunID, Status, ErrorCode, DurationSeconds, Context
			)
			VALUES (
				CURRENT_TIMESTAMP(), S.PipelineName, S.WindowStart, S.WindowEnd, S.RowsMerged,
				S.LogLevel, S.Message, S.RunID, S.Status, S.ErrorCode, S.DurationSeconds, S.Context
			)
		"""

		job_config = bigquery.QueryJobConfig(
			query_parameters=[
				bigquery.ScalarQueryParameter("pipeline", "STRING", SCRIPT_NAME),
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
		delay_seconds = 1.0
		for attempt in range(1, 5):
			try:
				query_job = bq_client.query(merge_query, job_config=job_config)
				query_job.result(timeout=45)
				return
			except Exception as attempt_error:
				if attempt == 4:
					raise
				logger.warning(
					"PipelineRuns log attempt %s failed for RunID %s (%s). Retrying in %.1fs.",
					attempt,
					run_id,
					attempt_error,
					delay_seconds,
				)
				time.sleep(delay_seconds)
				delay_seconds = min(delay_seconds * 2, 8.0)
	except Exception as exc:
		logger.warning("log_pipeline_run failed: %s", exc)


def parse_pubsub_payload(payload_text: str) -> Dict[str, Any]:
	"""Parse Pub/Sub payload in a tolerant way for different publisher formats."""
	raw = (payload_text or "").strip()
	if not raw:
		return {}

	try:
		parsed = json.loads(raw)
		if isinstance(parsed, dict):
			return parsed
	except json.JSONDecodeError:
		pass

	if raw.startswith("{") and raw.endswith("}"):
		try:
			parsed_literal = ast.literal_eval(raw)
			if isinstance(parsed_literal, dict):
				return {str(k): v for k, v in parsed_literal.items()}
		except Exception:
			pass

	return {"messageId": raw}


@functions_framework.cloud_event
def process_bq_bmc_user_list_email(cloud_event):
	"""Pub/Sub-triggered entrypoint for BMC User List processing."""
	global _script_start_time, _current_run_id

	_current_run_id = os.urandom(16).hex()
	_script_start_time = datetime.utcnow()

	log_pipeline_run(_current_run_id, "RUNNING", "INFO", "Pipeline run started")

	try:
		pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
		message_data = parse_pubsub_payload(pubsub_message)

		message_id = message_data.get("messageId")
		if not message_id:
			raise ValueError("Pub/Sub message missing messageId")

		message_subject = (message_data.get("subject") or "").strip()
		if message_subject and message_subject != EXPECTED_SUBJECT:
			logger.info("Skipping message %s due to subject mismatch: %s", message_id, message_subject)
			return

		service = get_gmail_service()
		message = get_message(service, message_id)
		actual_subject = get_message_subject(message)
		if actual_subject and actual_subject.strip() != EXPECTED_SUBJECT:
			logger.info("Skipping message %s due to actual subject mismatch: %s", message_id, actual_subject)
			return

		attachment_name = None
		for part in message.get("payload", {}).get("parts", []):
			filename = part.get("filename", "")
			if filename.lower().endswith(".csv"):
				attachment_name = filename
				break

		if not attachment_name:
			raise ValueError(f"No CSV attachment found for message {message_id}")

		csv_data = get_message_attachment(service, message_id, attachment_name)
		if not csv_data:
			raise ValueError(f"Could not retrieve CSV attachment: {attachment_name}")

		records = csv_to_records(csv_data)
		logger.info("Parsed %s records from %s", len(records), attachment_name)

		total_rows = 0
		for table in TARGET_TABLES:
			total_rows += write_records_to_table(table, records)

		manage_gmail_labels(service, message_id, GMAIL_LABEL_TO_REMOVE, GMAIL_LABEL_TO_ADD)

		log_pipeline_run(
			_current_run_id,
			"SUCCESS",
			"INFO",
			"Pipeline finished",
			rows_merged=total_rows,
		)
		logger.info("Pipeline run %s completed successfully", _current_run_id)

	except Exception as exc:
		logger.error("Pipeline error: %s", exc)
		log_pipeline_run(_current_run_id, "ERROR", "ERROR", str(exc))
		raise
