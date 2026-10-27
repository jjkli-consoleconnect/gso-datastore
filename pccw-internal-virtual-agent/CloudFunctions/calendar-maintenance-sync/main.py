"""
Cloud Function: Remedy Maintenance -> Google Calendar Sync
=========================================================
Syncs maintenance times from BigQuery to Google Calendar daily.

Reads:  pccw-internal-virtual-agent.Admin.RemedyMaintenance
Writes: Google Calendar (group calendar)

Trigger: Cloud Scheduler (daily 07:00 HKT)

Data sync model:
  - Incrementally pulls rows where LastModifiedDate >= 1 day before run time
    so only changed/added rows are processed (no full table scan, no gaps).
  - Upserts calendar events keyed by Incident_Number + Scheduled_Start_Date.
"""

import argparse
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import functions_framework
from google.cloud import bigquery, secretmanager
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from calendar_auth import (
    CalendarAuthError,
    EXPECTED_USER_EMAIL,
    require_calendar_write_access,
    verified_user_credentials,
)
from shared.logging_config import setup_root_logging
from shared.pipeline_runs_logger import log_pipeline_run

setup_root_logging()
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("TARGET_PROJECT", "pccw-internal-virtual-agent")
CALENDAR_ID = os.environ.get(
    "CALENDAR_ID",
    "c_d2bb391636ca477681527cabaa16d3a60acf512c30530a922f4c4db04c62a86c@group.calendar.google.com",
)
OAUTH_SECRET = os.environ.get("CALENDAR_OAUTH_SECRET", "google-calendar-user-oauth")
SRC_DATASET = "Admin"
SRC_TABLE = "RemedyMaintenance"
LAST_MODIFIED_COL = "LastModifiedDate"
SYNC_WINDOW_HOURS = int(os.environ.get("SYNC_WINDOW_HOURS", "24"))


def get_bq_client():
    return bigquery.Client(project=PROJECT_ID)


def build_merge_query():
    cutoff = f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {SYNC_WINDOW_HOURS} HOUR)"
    return f"""
        SELECT
            Incident_Number,
            Customer_Name,
            Planner,
            RPO_UMW_Reason,
            Scheduled_Start_Date,
            Scheduled_End_Date,
            LastModifiedDate
        FROM `{PROJECT_ID}.{SRC_DATASET}.{SRC_TABLE}`
        WHERE {LAST_MODIFIED_COL} >= {cutoff}
        ORDER BY Scheduled_Start_Date ASC
    """

# Calendar helpers
def get_calendar_service():
    # ADC is used only to read Secret Manager, never to authorize Calendar.
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{OAUTH_SECRET}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    try:
        info = json.loads(response.payload.data)
    except (ValueError, UnicodeDecodeError):
        raise CalendarAuthError("Calendar OAuth secret is not valid JSON.") from None
    if not isinstance(info, dict):
        raise CalendarAuthError("Calendar OAuth secret must be an authorized_user JSON object.")
    credentials = verified_user_credentials(info)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    require_calendar_write_access(service, CALENDAR_ID)
    return service


def build_event_body(row, *, create_conference=False):
    if not row.Scheduled_Start_Date or not row.Scheduled_End_Date:
        raise ValueError("Scheduled start and end dates are required")
    if row.Scheduled_End_Date <= row.Scheduled_Start_Date:
        raise ValueError("Scheduled end must be after scheduled start")
    body = {
        "summary": f"{row.Incident_Number} - {row['Customer_Name']}",
        "description": f"Planner: {row.Planner}\n\nRPO_UMW_Reason: {row.RPO_UMW_Reason}",
        "start": {
            "dateTime": row.Scheduled_Start_Date.isoformat(),
            "timeZone": "Asia/Hong_Kong",
        },
        "end": {
            "dateTime": row.Scheduled_End_Date.isoformat(),
            "timeZone": "Asia/Hong_Kong",
        },
    }
    if create_conference:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    return body


def event_id_for_row(row):
    start = row.Scheduled_Start_Date
    # BigQuery TIMESTAMP values are UTC. Preserve that interpretation for naive inputs.
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    key = f"RemedyMaintenance:{row.Incident_Number}:{start.astimezone(timezone.utc).isoformat()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upsert_calendar_event(service, row) -> str:
    event_id = event_id_for_row(row)
    try:
        service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    except HttpError as error:
        if error.resp.status != 404:
            raise
        body = build_event_body(row, create_conference=True)
        body["id"] = event_id
        try:
            service.events().insert(
                calendarId=CALENDAR_ID, body=body, sendUpdates="all", conferenceDataVersion=1
            ).execute()
            return "created"
        except HttpError as insert_error:
            # A concurrent run may have created the same deterministic ID.
            if insert_error.resp.status != 409:
                raise

    service.events().patch(
        calendarId=CALENDAR_ID,
        eventId=event_id,
        body=build_event_body(row),
        sendUpdates="all",
        conferenceDataVersion=1,
    ).execute()
    return "updated"


# Main entry point
@functions_framework.http
def sync_maintenance_to_calendar(request):
    run_id = str(uuid.uuid4())
    start_time = datetime.utcnow()
    logger.info(f"Pipeline run started: {run_id}")

    bq_client = None
    events_created = 0
    events_updated = 0
    events_errored = 0
    processed_rows = 0

    try:
        calendar_service = get_calendar_service()
        if request is not None and request.args.get("mode") == "check-auth":
            return {
                "status": "AUTHORIZED",
                "user": EXPECTED_USER_EMAIL,
                "calendar_id": CALENDAR_ID,
            }, 200
        bq_client = get_bq_client()
        query = build_merge_query()
        logger.info(f"Running incremental query: {query}")

        query_job = bq_client.query(query)
        results = list(query_job.result())
        processed_rows = len(results)
        logger.info(f"Fetched {processed_rows} rows from BigQuery")

        logger.info("Authorized to write target calendar: %s", CALENDAR_ID)

        for row in results:
            incident = row.Incident_Number
            start_date = row.Scheduled_Start_Date
            if not incident or not start_date:
                logger.warning(
                    f"Skipping row with missing Incident_Number or Scheduled_Start_Date"
                )
                events_errored += 1
                continue

            try:
                result = upsert_calendar_event(calendar_service, row)
                if result == "created":
                    events_created += 1
                else:
                    events_updated += 1
                logger.info("Calendar event %s: %s", result, incident)
            except HttpError as error:
                if error.resp.status in (401, 403, 404):
                    raise CalendarAuthError(
                        f"Calendar write failed with HTTP {error.resp.status}; "
                        "check user consent, calendar ID, Workspace policy and writer access."
                    ) from None
                logger.error("Calendar event failed: incident=%s HTTP=%s", incident, error.resp.status)
                events_errored += 1
            except (ValueError, TypeError) as error:
                logger.error("Invalid calendar event: incident=%s error=%s", incident, error)
                events_errored += 1

        # Log pipeline run
        duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        status = "SUCCESS" if events_errored == 0 else "PARTIAL_FAILURE"

        log_pipeline_run(
            client=bq_client,
            pipeline_name="RemedyMaintenance_to_Calendar",
            run_id=run_id,
            level="INFO" if events_errored == 0 else "ERROR",
            message=(
                f"Sync complete: {events_created} created, "
                f"{events_updated} updated, {events_errored} errors"
            ),
            status=status,
            rows_merged=events_created + events_updated,
            window_start=None,
            window_end=None,
            duration_seconds=duration_seconds,
            project=PROJECT_ID,
        )

        logger.info(
            f"Pipeline run completed: {events_created} created, "
            f"{events_updated} updated, {events_errored} errors"
        )

        response = {
            "status": status,
            "created": events_created,
            "updated": events_updated,
            "errors": events_errored,
            "rows_processed": processed_rows,
        }
        return response, 200 if events_errored == 0 else 500

    except Exception as err:
        logger.error(f"Pipeline run failed: {err}")
        if bq_client is not None:
            log_pipeline_run(
                client=bq_client,
                pipeline_name="RemedyMaintenance_to_Calendar",
                run_id=run_id,
                level="ERROR",
                message=f"Pipeline run failed: {err}",
                status="FAILED",
                error_code=str(err),
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                project=PROJECT_ID,
            )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only Calendar OAuth verification; never runs the sync.")
    parser.add_argument("--credentials-file", help="Explicit authorized_user JSON to verify before publishing.")
    args = parser.parse_args()
    if args.credentials_file:
        with open(args.credentials_file, encoding="utf-8") as handle:
            user_info = json.load(handle)
        if not isinstance(user_info, dict):
            raise CalendarAuthError("OAuth credentials must be a JSON object.")
        user_credentials = verified_user_credentials(user_info)
        calendar = build("calendar", "v3", credentials=user_credentials, cache_discovery=False)
        require_calendar_write_access(calendar, CALENDAR_ID)
    else:
        get_calendar_service()
