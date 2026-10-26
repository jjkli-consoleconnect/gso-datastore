import argparse
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

REAL_BIGQUERY_CLASSES = {
    name: getattr(bigquery, name)
    for name in (
        "Client",
        "QueryJobConfig",
        "ScalarQueryParameter",
        "ArrayQueryParameter",
        "SchemaField",
        "LoadJobConfig",
        "SourceFormat",
        "WriteDisposition",
    )
}

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "pccw-internal-virt-agent-uat"
PROD_PROJECT = "pccw-internal-virtual-agent"
TOPIC = "gmail-to-bq-hdwl"
ERROR_WINDOW_HOURS = 36
EXPECTED_SUBJECTS = {"pubsub - HDWL", "pubsub - BQ - GSO.HDWL"}
EXPECTED_SENDER = "noreply-bmchelix@onbmc.com"


def request_json(url, token, body=None, content_type="application/json"):
    request = Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        method="GET" if body is None else "POST",
    )
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def load_processor():
    test_path = ROOT / "pccw-internal-virt-agent-uat" / "CloudFunctions" / "bq_hdwl" / "test_main.py"
    sys.path.insert(0, str(test_path.parent))
    test_spec = importlib.util.spec_from_file_location("hdwl_regression_suite", test_path)
    test_module = importlib.util.module_from_spec(test_spec)
    test_spec.loader.exec_module(test_module)
    for name, value in REAL_BIGQUERY_CLASSES.items():
        setattr(bigquery, name, value)
    deployed_path = ROOT / "Temp" / "hdwl_rpo_fix" / "uat" / "source" / "main.py"
    deployed_spec = importlib.util.spec_from_file_location("deployed_hdwl_uat", deployed_path)
    processor = importlib.util.module_from_spec(deployed_spec)
    deployed_spec.loader.exec_module(processor)
    return processor


def get_failed_message_ids(client):
    query = f"""WITH message_runs AS (
            SELECT 'UAT' AS environment, RunTime, Status, Message,
                JSON_VALUE(Context, '$.messageId') AS message_id
            FROM `{PROJECT}.GSO.PipelineRuns`
            WHERE PipelineName='pubsub - HDWL'
                AND RunTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {ERROR_WINDOW_HOURS} HOUR)
                AND JSON_VALUE(Context, '$.messageId') IS NOT NULL
            UNION ALL
            SELECT 'Prod' AS environment, RunTime, Status, Message,
                JSON_VALUE(Context, '$.messageId') AS message_id
            FROM `{PROD_PROJECT}.Datapipe.PipelineRuns`
            WHERE PipelineName='pubsub - HDWL'
                AND RunTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {ERROR_WINDOW_HOURS} HOUR)
                AND JSON_VALUE(Context, '$.messageId') IS NOT NULL
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY environment, message_id ORDER BY RunTime DESC
            ) AS rn
            FROM message_runs
        )
        SELECT DISTINCT message_id FROM ranked
        WHERE rn=1 AND Status='ERROR'
            AND STARTS_WITH(Message, 'Attachment processing incomplete. Failed:')
        ORDER BY message_id"""
    return [row.message_id for row in client.query(
        query, location="EU",
        job_config=bigquery.QueryJobConfig(labels={"datacloud": "vscode"}),
    ).result()]


def get_terminal_audits(client, message_id, published_at):
    if not message_id.isalnum():
        raise ValueError(f"Unexpected Gmail message ID: {message_id}")
    query = f"""WITH runs AS (
      SELECT 'UAT' AS environment, RunTime, Status
      FROM `{PROJECT}.GSO.PipelineRuns`
      WHERE PipelineName='pubsub - HDWL'
        AND JSON_VALUE(Context, '$.messageId')='{message_id}'
        AND RunTime>=@published_at
      UNION ALL
      SELECT 'Prod' AS environment, RunTime, Status
      FROM `{PROD_PROJECT}.Datapipe.PipelineRuns`
      WHERE PipelineName='pubsub - HDWL'
        AND JSON_VALUE(Context, '$.messageId')='{message_id}'
        AND RunTime>=@published_at
    )
    SELECT environment, Status FROM runs
    QUALIFY ROW_NUMBER() OVER (PARTITION BY environment ORDER BY RunTime DESC)=1"""
    query_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("published_at", "TIMESTAMP", published_at)],
        labels={"datacloud": "vscode"},
    )
    statuses = {row.environment: row.Status for row in client.query(
        query, location="EU", job_config=query_config,
    ).result()}
    ledger_query = f"""SELECT COUNT(*) AS completed
      FROM `{PROD_PROJECT}.Datapipe.ProcessedPubSubMessages`
      WHERE pipeline_name='pubsub - HDWL' AND message_id='{message_id}'"""
    ledger_row = next(iter(client.query(
        ledger_query, location="EU",
        job_config=bigquery.QueryJobConfig(labels={"datacloud": "vscode"}),
    ).result()))
    if ledger_row.completed:
        statuses.setdefault("Prod", "SUCCESS")
    return statuses


def wait_for_both_successes(client, message_id, published_at, timeout_seconds=900):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        statuses = get_terminal_audits(client, message_id, published_at)
        failed = {environment: status for environment, status in statuses.items()
                  if status == "ERROR"}
        if failed:
            raise RuntimeError(f"HDWL recovery failed for {message_id}: {failed}")
        if statuses.get("UAT") == "SUCCESS" and statuses.get("Prod") == "SUCCESS":
            return statuses
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for UAT/Prod audits for {message_id}")


def gmail_credentials_token(gcloud):
    secret = subprocess.run(
        [gcloud, "secrets", "versions", "access", "latest", "--secret",
         "gmail-oauth-token", "--project", PROJECT],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(secret)
    form = urlencode({
        "client_id": data["client_id"],
        "client_secret": data["client_secret"],
        "refresh_token": data["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    return request_json(data["token_uri"], "", form,
                        "application/x-www-form-urlencoded")["access_token"]


def walk_parts(part):
    yield part
    for child in part.get("parts", []):
        yield from walk_parts(child)


def fetch_attachment(message_id, part, gmail_token):
    body = part.get("body", {})
    if body.get("data"):
        encoded = body["data"]
    else:
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            raise ValueError(f"Attachment has no data: {part.get('filename')}")
        result = request_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
            f"{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}",
            gmail_token,
        )
        encoded = result["data"]
    return base64.urlsafe_b64decode(encoded + "=" * ((-len(encoded)) % 4))


def validate_message(message_id, processor, gmail_token):
    message = request_json(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id, safe='')}?format=full",
        gmail_token,
    )
    message_headers = {
        header.get("name", "").lower(): header.get("value", "")
        for header in message.get("payload", {}).get("headers", [])
    }
    if message_headers.get("subject", "").strip() not in EXPECTED_SUBJECTS:
        raise ValueError(f"Unexpected HDWL source subject for {message_id}")
    if EXPECTED_SENDER.lower() not in message_headers.get("from", "").lower():
        raise ValueError(f"Unexpected HDWL source sender for {message_id}")
    config_by_prefix = {
        config["filename_prefix"].lower(): config
        for config in processor.CSV_CONFIGURATIONS
    }
    found = set()
    attachment_results = []
    for part in walk_parts(message.get("payload", {})):
        filename = part.get("filename", "")
        if not filename.lower().endswith(".csv"):
            continue
        config = next((cfg for prefix, cfg in config_by_prefix.items()
                       if filename.lower().startswith(prefix)), None)
        if config is None:
            raise ValueError(f"Unmatched CSV attachment {filename}")
        found.add(config["name"])
        payload = fetch_attachment(message_id, part, gmail_token)
        if not payload:
            raise ValueError(f"Empty attachment payload: {filename}")
        reason = processor.detect_known_non_data_payload(payload)
        if reason:
            raise ValueError(f"Known upstream payload ({reason}): {filename}")
        rows = processor.robust_parse_csv(payload, config)
        header_index = processor.locate_header_row(rows, config)
        headers = [processor.standardize_field_name(h, config["field_map"])
                   for h in rows[header_index]]
        unknown = sorted(set(headers) - set(config["all_columns"]))
        if unknown:
            raise ValueError(f"Unmapped source columns in {filename}: {unknown}")
        data_rows = rows[header_index + 1:]
        if len(data_rows) < processor.MIN_VALID_CSV_DATA_ROWS:
            raise ValueError(f"Too few source rows in {filename}: {len(data_rows)}")
        usable = 0
        over_width = 0
        for row in data_rows:
            if processor.is_non_data_artifact_row(row) or processor.is_worklog_forwarded_body_row(row, headers, config):
                continue
            repaired = processor.repair_trailing_text_overflow(row, headers, config)
            if repaired is not None:
                row = repaired
            if len(row) != len(headers):
                if len(row) > len(headers):
                    over_width += 1
                continue
            usable += 1
            if "VIP" in headers:
                processor.normalize_vip_value(
                    processor.handle_empty_values(row[headers.index("VIP")], False, False)
                )
        candidates = usable + over_width
        if over_width and candidates and over_width / candidates > processor.MAX_RAGGED_ROW_RATIO:
            raise ValueError(f"Too many over-width rows in {filename}: {over_width}/{candidates}")
        if not usable:
            raise ValueError(f"No usable data rows in {filename}")
        attachment_results.append({"filename": filename, "source_data_rows": len(data_rows), "usable_rows": usable})
    expected = {cfg["name"] for cfg in processor.CSV_CONFIGURATIONS}
    if found != expected:
        raise ValueError(f"Expected configs {sorted(expected)}, found {sorted(found)}")
    return {
        "message_id": message_id,
        "received_internal_ms": int(message.get("internalDate", "0") or 0),
        "attachments": attachment_results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true",
                        help="Publish only after every currently failed report validates")
    args = parser.parse_args()
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    token = subprocess.run([gcloud, "auth", "print-access-token"],
                           check=True, capture_output=True, text=True).stdout.strip()
    creds = Credentials(token=token)
    client = bigquery.Client(project=PROJECT, credentials=creds)
    message_ids = get_failed_message_ids(client)
    if not message_ids:
        print("No unresolved failed source messages in the last 36 hours.")
        return
    processor = load_processor()
    gmail_token = gmail_credentials_token(gcloud)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(
            lambda mid: validate_message(mid, processor, gmail_token), message_ids
        ))
    results.sort(key=lambda report: report["received_internal_ms"])
    message_ids = [report["message_id"] for report in results]
    print(json.dumps({"validated_messages": len(results), "reports": results}, indent=2))
    if not args.publish:
        print("DRY RUN ONLY: no Pub/Sub messages published.")
        return
    for message_id in message_ids:
        payload = json.dumps({"messageId": message_id, "subject": "pubsub - HDWL", "backfill": True})
        published_at = datetime.now(timezone.utc)
        publish_body = json.dumps({"messages": [{
            "data": base64.b64encode(payload.encode()).decode("ascii")
        }]}).encode()
        response = request_json(
            f"https://pubsub.googleapis.com/v1/projects/{PROJECT}/topics/{TOPIC}:publish",
            token, publish_body,
        )
        pubsub_id = response["messageIds"][0]
        print(f"PUBLISHED {message_id} as {pubsub_id}; waiting for UAT and Prod", flush=True)
        statuses = wait_for_both_successes(client, message_id, published_at)
        print(f"CONFIRMED {message_id}: {statuses}", flush=True)


if __name__ == "__main__":
    main()
