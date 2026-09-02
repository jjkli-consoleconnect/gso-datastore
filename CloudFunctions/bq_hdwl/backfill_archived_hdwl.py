#!/usr/bin/env python3
"""Replay archived HDWL Gmail snapshots to the existing Pub/Sub topic.

This utility republishes archived HDWL messages oldest-first so the
process-bq-hdwl-email function can re-ingest missed snapshots safely.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request as UrlRequest, urlopen

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest


PROJECT_ID = "pccw-internal-virt-agent-uat"
TOPIC_NAME = "gmail-to-bq-hdwl"
SECRET_NAME = "gmail-oauth-token"
ARCHIVE_LABEL = "ArchivedReports"
REPLAY_LABELS = (ARCHIVE_LABEL, "pubsub")
HDWL_SUBJECTS = {
    "pubsub - HDWL",
    "pubsub - BQ - GSO.HDWL",
}
HDWL_FROM = "noreply-bmchelix@onbmc.com"
PIPELINE_RUNS_TABLE = f"{PROJECT_ID}.GSO.PipelineRuns"
PIPELINE_NAME_PREFIX = "pubsub - HDWL"


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    internal_date_ms: int
    subject: str
    sender: str


def resolve_gcloud_command() -> List[str]:
    candidate = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if candidate:
        return [candidate]

    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
    if fallback.exists():
        return [str(fallback)]

    raise FileNotFoundError("Could not locate gcloud.cmd or gcloud in PATH")


def resolve_bq_command() -> List[str]:
    candidate = shutil.which("bq.cmd") or shutil.which("bq")
    if candidate:
        return [candidate]

    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "bq.cmd"
    if fallback.exists():
        return [str(fallback)]

    raise FileNotFoundError("Could not locate bq.cmd or bq in PATH")


def run_gcloud_command(args: List[str]) -> str:
    completed = subprocess.run(
        [*resolve_gcloud_command(), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def get_access_token() -> str:
    return run_gcloud_command(["auth", "print-access-token"])


def load_oauth_credentials() -> Credentials:
    token_json = run_gcloud_command(
        [
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            SECRET_NAME,
            "--project",
            PROJECT_ID,
        ]
    )
    token_data = json.loads(token_json)
    return Credentials.from_authorized_user_info(token_data)


def get_gmail_credentials() -> Credentials:
    creds = load_oauth_credentials()
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
    return creds


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def metadata_to_message(message: dict) -> GmailMessage:
    headers = message.get("payload", {}).get("headers", [])
    subject = next((header["value"] for header in headers if header.get("name", "").lower() == "subject"), "")
    sender = next((header["value"] for header in headers if header.get("name", "").lower() == "from"), "")
    return GmailMessage(
        message_id=message["id"],
        internal_date_ms=int(message.get("internalDate", "0") or 0),
        subject=subject,
        sender=sender,
    )


def gmail_api_get(creds: Credentials, path: str, params: Optional[dict] = None) -> dict:
    base_url = f"https://gmail.googleapis.com/gmail/v1/{path.lstrip('/')}"
    if params:
        base_url = f"{base_url}?{urlencode(params, doseq=True)}"

    for attempt in range(3):
        request = UrlRequest(base_url, headers={"Authorization": f"Bearer {creds.token}"})
        try:
            with urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 401 and attempt < 2:
                try:
                    creds.refresh(GoogleAuthRequest())
                except Exception:
                    # Fall back to reloading OAuth credentials from Secret Manager.
                    replacement = get_gmail_credentials()
                    creds.token = replacement.token
                    creds.refresh_token = replacement.refresh_token
                    creds.expiry = replacement.expiry
                continue
            raise

    raise RuntimeError("Gmail API request failed after retry")


def resolve_archive_label(creds: Credentials) -> Optional[str]:
    response = gmail_api_get(creds, "users/me/labels")
    labels = response.get("labels", [])

    exact_matches = [label.get("name") for label in labels if label.get("name", "").lower() == ARCHIVE_LABEL.lower()]
    if exact_matches:
        return exact_matches[0]

    fuzzy_matches = [
        label.get("name")
        for label in labels
        if "archive" in label.get("name", "").lower()
    ]
    if fuzzy_matches:
        return fuzzy_matches[0]

    return None


def list_replay_messages(
    service,
    since_utc: datetime,
    replay_labels: List[str],
    max_results: Optional[int] = None,
    label_only: bool = False,
) -> List[GmailMessage]:
    candidates: List[GmailMessage] = []
    subjects_query = " OR ".join([f'subject:"{subject}"' for subject in sorted(HDWL_SUBJECTS)])

    for search_label in replay_labels:
        query_parts = [
            f"label:{search_label}",
            f"after:{since_utc.strftime('%Y/%m/%d')}",
            f"from:{HDWL_FROM}",
        ]
        if not label_only:
            query_parts.append(f"({subjects_query})")
        query = " ".join(query_parts)
        page_token = None

        while True:
            params = {"q": query, "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            response = gmail_api_get(service, "users/me/messages", params)

            for item in response.get("messages", []):
                try:
                    message = gmail_api_get(
                        service,
                        f"users/me/messages/{quote(item['id'])}",
                        {"format": "metadata", "metadataHeaders": ["Subject", "From"]},
                    )
                    parsed = metadata_to_message(message)
                    if not label_only and parsed.subject.strip() not in HDWL_SUBJECTS:
                        continue
                    if parsed.internal_date_ms >= int(since_utc.timestamp() * 1000):
                        candidates.append(parsed)
                except Exception as error:
                    logger.warning("Skipping Gmail message %s due to API error: %s", item.get("id"), error)

                if max_results is not None and len(candidates) >= max_results:
                    break

            if max_results is not None and len(candidates) >= max_results:
                break

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        if max_results is not None and len(candidates) >= max_results:
            break

    candidates.sort(key=lambda item: item.internal_date_ms)

    unique_candidates: List[GmailMessage] = []
    seen_ids = set()
    for candidate in candidates:
        if candidate.message_id in seen_ids:
            continue
        seen_ids.add(candidate.message_id)
        unique_candidates.append(candidate)

    return unique_candidates


def publish_message_id(message: GmailMessage) -> None:
    payload = {
        "messageId": message.message_id,
        "subject": message.subject.strip(),
        "from": message.sender,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backfill": True,
    }
    request_body = json.dumps({
        "messages": [
            {
                "data": base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii"),
            }
        ]
    }).encode("utf-8")

    publish_url = f"https://pubsub.googleapis.com/v1/projects/{PROJECT_ID}/topics/{TOPIC_NAME}:publish"
    request = UrlRequest(
        publish_url,
        data=request_body,
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request) as response:
        response.read()


def get_latest_pipeline_status_for_message(message_id: str, start_time_utc: datetime) -> Optional[str]:
    if not message_id or not message_id.replace("-", "").isalnum():
        raise ValueError(f"Unsafe message_id for SQL filter: {message_id}")

    start_ts = start_time_utc.strftime("%Y-%m-%d %H:%M:%S+00")
    query = (
        "SELECT Status "
        f"FROM `{PIPELINE_RUNS_TABLE}` "
        f"WHERE PipelineName LIKE '{PIPELINE_NAME_PREFIX}%' "
        f"AND JSON_VALUE(TO_JSON_STRING(Context), '$.messageId') = '{message_id}' "
        f"AND RunTime >= TIMESTAMP('{start_ts}') "
        "ORDER BY RunTime DESC "
        "LIMIT 1"
    )

    completed = subprocess.run(
        [
            *resolve_bq_command(),
            "query",
            "--project_id",
            PROJECT_ID,
            "--use_legacy_sql=false",
            "--format=json",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip()
    if not output:
        return None
    rows = json.loads(output)
    if not rows:
        return None
    return rows[0].get("Status")


def wait_for_message_terminal_status(message_id: str, start_time_utc: datetime, timeout_seconds: int, poll_seconds: int) -> Optional[str]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = get_latest_pipeline_status_for_message(message_id, start_time_utc)
        if status in {"SUCCESS", "ERROR"}:
            return status
        time.sleep(poll_seconds)
    return None


def build_since_window(args: argparse.Namespace) -> datetime:
    if args.since:
        since = parse_timestamp(args.since)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)
    return since - timedelta(minutes=args.overlap_minutes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay archived HDWL Gmail messages to Pub/Sub.")
    parser.add_argument("--since", help="UTC timestamp for the beginning of the replay window (ISO 8601)")
    parser.add_argument("--lookback-hours", type=float, default=24.0, help="Fallback lookback window when --since is omitted")
    parser.add_argument("--overlap-minutes", type=float, default=30.0, help="Replay a small overlap before the start time")
    parser.add_argument("--dry-run", action="store_true", help="Print matched message IDs without publishing")
    parser.add_argument("--label-only", action="store_true", help="Ignore the HDWL subject/from filters and query by archive label only")
    parser.add_argument("--max-results", type=int, default=None, help="Optional cap on messages to replay")
    parser.add_argument("--queue-mode", action="store_true", help="Publish one message at a time and wait for terminal PipelineRuns status before next publish")
    parser.add_argument("--queue-timeout-seconds", type=int, default=900, help="Max seconds to wait per message in queue mode")
    parser.add_argument("--queue-poll-seconds", type=int, default=10, help="Polling interval seconds for queue mode status checks")
    parser.add_argument("--queue-continue-on-timeout", action="store_true", help="Continue publishing next message if queue-mode wait times out")
    parser.add_argument("--queue-continue-on-error", action="store_true", help="Continue publishing next message if queue-mode terminal status is ERROR")
    parser.add_argument("--publish-delay-seconds", type=float, default=0.0, help="Optional sleep between publishes when not using queue mode")
    args = parser.parse_args()

    since_window = build_since_window(args)
    logger.info("Replay window starts at %s UTC", since_window.isoformat())

    creds = get_gmail_credentials()
    archive_label = resolve_archive_label(creds)
    replay_labels = [label for label in (archive_label, *REPLAY_LABELS) if label]
    if replay_labels:
        logger.info("Using replay labels: %s", ", ".join(dict.fromkeys(replay_labels)))
    else:
        logger.warning("No replay labels matched; falling back to subject/from only")

    messages = list_replay_messages(
        creds,
        since_window,
        replay_labels,
        max_results=args.max_results,
        label_only=args.label_only,
    )

    logger.info("Matched %s HDWL replay candidates", len(messages))
    for message in messages:
        message_time = datetime.fromtimestamp(message.internal_date_ms / 1000.0, tz=timezone.utc)
        logger.info("%s %s %s", message_time.isoformat(), message.message_id, message.subject)

    if args.dry_run:
        logger.info("Dry run complete; no messages published.")
        return 0

    for index, message in enumerate(messages, start=1):
        logger.info("Publishing %s/%s: %s", index, len(messages), message.message_id)
        published_at = datetime.now(timezone.utc)
        publish_message_id(message)

        if args.queue_mode:
            logger.info(
                "Queue mode: waiting up to %ss for terminal status on message %s",
                args.queue_timeout_seconds,
                message.message_id,
            )
            terminal_status = wait_for_message_terminal_status(
                message.message_id,
                published_at,
                args.queue_timeout_seconds,
                args.queue_poll_seconds,
            )
            if terminal_status is None:
                timeout_msg = (
                    f"Queue wait timed out for message {message.message_id} after "
                    f"{args.queue_timeout_seconds}s"
                )
                if args.queue_continue_on_timeout:
                    logger.warning(timeout_msg + "; continuing due to --queue-continue-on-timeout")
                else:
                    logger.error(timeout_msg)
                    return 1

            if terminal_status == "ERROR":
                error_msg = f"Queue mode observed terminal ERROR for message {message.message_id}"
                if args.queue_continue_on_error:
                    logger.warning(error_msg + "; continuing due to --queue-continue-on-error")
                else:
                    logger.error(error_msg)
                    return 1

            if terminal_status == "SUCCESS":
                logger.info("Queue mode: message %s completed with SUCCESS", message.message_id)
        elif args.publish_delay_seconds > 0:
            time.sleep(args.publish_delay_seconds)

    logger.info("Replay complete. Published %s HDWL messages.", len(messages))
    return 0


if __name__ == "__main__":
    sys.exit(main())