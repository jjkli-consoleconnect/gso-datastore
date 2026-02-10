import functions_framework
import logging
import json
import uuid
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.cloud import bigquery
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError

from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run
from secrets_manager import get_secret

# Setup logging
setup_root_logging()

# PagerDuty API config
PAGERDUTY_API_BASE = "https://api.pagerduty.com"

def pagerduty_request(endpoint: str, token: str, params: Dict[str, Any] = None, limit: int = 100) -> Optional[List]:
    """Make paginated PagerDuty API request."""
    if not params:
        params = {}
    
    params["limit"] = limit
    offset = 0
    all_data = []
    
    while True:
        params["offset"] = offset
        
        headers = {
            "Authorization": f"Token token={token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.pagerduty+json;version=2"
        }
        
        try:
            response = requests.get(
                f"{PAGERDUTY_API_BASE}{endpoint}",
                headers=headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract the resource key
            resource_key = None
            for key in data.keys():
                if key not in ["limit", "offset", "total", "more"]:
                    resource_key = key
                    break
            
            if resource_key and data.get(resource_key):
                all_data.extend(data[resource_key])
            
            if not data.get("more"):
                break
            
            offset += limit
            
        except requests.exceptions.RequestException as e:
            logging.error(f"PagerDuty API error on {endpoint}: {e}")
            return None
    
    return all_data

def build_entity_id(entity_type: str, item: Dict[str, Any]) -> Optional[str]:
    if entity_type == "oncalls":
        schedule = item.get("schedule")
        user = item.get("user")
        start = item.get("start")
        end = item.get("end")
        schedule_id = schedule.get("id") if schedule else None
        user_id = user.get("id") if user else None
        if schedule_id and user_id and start:
            # Use schedule_user_start_end as unique key
            end_str = end if end else "ongoing"
            return f"{schedule_id}_{user_id}_{start}_{end_str}"
        return None
    return item.get("id")


def build_parent_id(entity_type: str, item: Dict[str, Any]) -> Optional[str]:
    if entity_type == "alerts":
        incident = item.get("incident")
        return incident.get("id") if incident else None
    if entity_type == "oncalls":
        schedule = item.get("schedule")
        return schedule.get("id") if schedule else None
    if entity_type == "incidents":
        service = item.get("service")
        return service.get("id") if service else None
    return None


def extract_summaries(items_array: Optional[List[Dict[str, Any]]]) -> List[str]:
    """Extract 'summary' field from array of objects."""
    if not items_array:
        return []
    summaries = []
    for item in items_array:
        if isinstance(item, dict) and "summary" in item:
            summaries.append(item.get("summary"))
    return summaries


def build_entity_row(entity_type: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entity_id = build_entity_id(entity_type, item)
    if not entity_id:
        return None

    # Common fields
    created_at = item.get("created_at") or item.get("start")
    updated_at = (
        item.get("updated_at")
        or item.get("last_status_change_at")
        or item.get("end")
        or created_at
    )
    name = item.get("name") or item.get("summary")
    summary = item.get("summary") or item.get("title") or item.get("description")
    status = item.get("status") or item.get("urgency")

    # Initialize row with ALL fields (prevents BigQuery from ignoring columns)
    row = {
        "EntityType": entity_type,
        "EntityId": entity_id,
        "ParentId": build_parent_id(entity_type, item),
        "Name": name,
        "Summary": summary,
        "Status": status,
        "HtmlUrl": item.get("html_url"),
        "CreatedAt": created_at,
        "UpdatedAt": updated_at,
        # Common optional fields
        "IncidentNumber": None,
        "Urgency": None,
        "Title": None,
        "Description": None,
        "ImpactedServices": None,
        "EscalationPolicyId": None,
        "FirstTriggeredAt": None,
        "LastStatusChangeAt": None,
        "LastStatusChangeBy": None,
        "FirstResolvedAt": None,
        "LastResolvedAt": None,
        "ServiceStatus": None,
        "ServiceDescription": None,
        "AutoResolveTimeout": None,
        "AcknowledgementTimeout": None,
        "DefaultEscalationPolicyId": None,
           "ServiceTeamSummaries": [],
           "ServiceIntegrationSummaries": [],
           "Email": None,
           "UserStatus": None,
           "AvatarUrl": None,
           "UserRole": None,
           "TimeZone": None,
           "UserTeamSummaries": [],
           "TeamDescription": None,
           "MemberSummaries": [],
           "ScheduleTimeZone": None,
           "ScheduleLayerSummaries": [],
           "OverrideSummaries": [],
           "FinalSchedule": None,
           "NumLayers": None,
           "RepeatEnabled": None,
           "EscalationRuleSummaries": [],
           "UserId": None,
           "ScheduleId": None,
           "OnCallStart": None,
           "OnCallEnd": None,
           "OnCallLevel": None,
           "AlertStatus": None,
           "AlertBody": None,
           "AlertCreatedAt": None,
    }

    # Entity-specific field extraction
    if entity_type == "incidents":
        row["IncidentNumber"] = item.get("incident_number")
        row["Urgency"] = item.get("urgency")
        row["Title"] = item.get("title")
        row["Description"] = item.get("description")
        row["ImpactedServices"] = json.dumps(item.get("services", []), ensure_ascii=False) if item.get("services") else None
        escalation_policy = item.get("escalation_policy")
        row["EscalationPolicyId"] = escalation_policy.get("id") if escalation_policy else None
        row["FirstTriggeredAt"] = item.get("first_triggered_at")
        row["LastStatusChangeAt"] = item.get("last_status_change_at")
        row["LastStatusChangeBy"] = json.dumps(item.get("last_status_change_by"), ensure_ascii=False) if item.get("last_status_change_by") else None
        row["FirstResolvedAt"] = item.get("first_resolved_at")
        row["LastResolvedAt"] = item.get("last_resolved_at")
    
    elif entity_type == "services":
        row["ServiceStatus"] = item.get("status")
        row["ServiceDescription"] = item.get("description")
        row["AutoResolveTimeout"] = item.get("auto_resolve_timeout")
        row["AcknowledgementTimeout"] = item.get("acknowledgement_timeout")
        escalation_policy = item.get("escalation_policy")
        row["DefaultEscalationPolicyId"] = escalation_policy.get("id") if escalation_policy else None
        row["ServiceTeamSummaries"] = extract_summaries(item.get("teams"))
        row["ServiceIntegrationSummaries"] = extract_summaries(item.get("integrations"))
    
    elif entity_type == "users":
        row["Email"] = item.get("email")
        row["UserStatus"] = item.get("status")
        row["AvatarUrl"] = item.get("avatar_url")
        row["UserRole"] = item.get("role")
        row["TimeZone"] = item.get("time_zone")
        row["UserTeamSummaries"] = extract_summaries(item.get("teams"))
    
    elif entity_type == "teams":
        row["TeamDescription"] = item.get("description")
        row["MemberSummaries"] = extract_summaries(item.get("members"))
    
    elif entity_type == "schedules":
        row["ScheduleTimeZone"] = item.get("time_zone")
        row["ScheduleLayerSummaries"] = extract_summaries(item.get("schedule_layers"))
        row["OverrideSummaries"] = extract_summaries(item.get("overrides"))
        row["FinalSchedule"] = json.dumps(item.get("final_schedule"), ensure_ascii=False) if item.get("final_schedule") else None
    
    elif entity_type == "escalation_policies":
        row["NumLayers"] = item.get("num_layers")
        row["RepeatEnabled"] = item.get("repeat_enabled")
        row["EscalationRuleSummaries"] = extract_summaries(item.get("escalation_rules"))
    
    elif entity_type == "oncalls":
        user = item.get("user")
        schedule = item.get("schedule")
        row["UserId"] = user.get("id") if user else None
        row["ScheduleId"] = schedule.get("id") if schedule else None
        row["OnCallStart"] = item.get("start")
        row["OnCallEnd"] = item.get("end")
        row["OnCallLevel"] = item.get("escalation_level")
    
    elif entity_type == "alerts":
        row["AlertStatus"] = item.get("status")
        row["AlertBody"] = json.dumps(item.get("body"), ensure_ascii=False) if item.get("body") else None
        row["AlertCreatedAt"] = item.get("created_at")

    # Always include raw JSON and sync time
    row["RawJson"] = json.dumps(item, ensure_ascii=False)
    row["SyncTime"] = datetime.now(timezone.utc).isoformat()

    return row

def create_or_replace_temp_table(client: bigquery.Client, dataset_id: str, temp_table_id: str) -> bool:
    """Create or replace a temporary staging table."""

    schema = [
        # Core identifiers
        bigquery.SchemaField("EntityType", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("EntityId", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("ParentId", "STRING"),
        
        # Common fields
        bigquery.SchemaField("Name", "STRING"),
        bigquery.SchemaField("Summary", "STRING"),
        bigquery.SchemaField("Status", "STRING"),
        bigquery.SchemaField("HtmlUrl", "STRING"),
        bigquery.SchemaField("CreatedAt", "TIMESTAMP"),
        bigquery.SchemaField("UpdatedAt", "TIMESTAMP"),
        
        # Incident fields
        bigquery.SchemaField("IncidentNumber", "STRING"),
        bigquery.SchemaField("Urgency", "STRING"),
        bigquery.SchemaField("Title", "STRING"),
        bigquery.SchemaField("Description", "STRING"),
        bigquery.SchemaField("ImpactedServices", "STRING"),
        bigquery.SchemaField("EscalationPolicyId", "STRING"),
        bigquery.SchemaField("FirstTriggeredAt", "TIMESTAMP"),
        bigquery.SchemaField("LastStatusChangeAt", "TIMESTAMP"),
        bigquery.SchemaField("LastStatusChangeBy", "STRING"),
        bigquery.SchemaField("FirstResolvedAt", "TIMESTAMP"),
        bigquery.SchemaField("LastResolvedAt", "TIMESTAMP"),
        
        # Service fields
        bigquery.SchemaField("ServiceStatus", "STRING"),
        bigquery.SchemaField("ServiceDescription", "STRING"),
        bigquery.SchemaField("AutoResolveTimeout", "INTEGER"),
        bigquery.SchemaField("AcknowledgementTimeout", "INTEGER"),
        bigquery.SchemaField("DefaultEscalationPolicyId", "STRING"),
        bigquery.SchemaField("ServiceTeamSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("ServiceIntegrationSummaries", "STRING", mode="REPEATED"),
        
        # User fields
        bigquery.SchemaField("Email", "STRING"),
        bigquery.SchemaField("UserStatus", "STRING"),
        bigquery.SchemaField("AvatarUrl", "STRING"),
        bigquery.SchemaField("UserRole", "STRING"),
        bigquery.SchemaField("TimeZone", "STRING"),
        bigquery.SchemaField("UserTeamSummaries", "STRING", mode="REPEATED"),
        
        # Team fields
        bigquery.SchemaField("TeamDescription", "STRING"),
        bigquery.SchemaField("MemberSummaries", "STRING", mode="REPEATED"),
        
        # Schedule fields
        bigquery.SchemaField("ScheduleTimeZone", "STRING"),
        bigquery.SchemaField("ScheduleLayerSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("OverrideSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("FinalSchedule", "STRING"),
        
        # Escalation Policy fields
        bigquery.SchemaField("NumLayers", "INTEGER"),
        bigquery.SchemaField("RepeatEnabled", "BOOLEAN"),
        bigquery.SchemaField("EscalationRuleSummaries", "STRING", mode="REPEATED"),
        
        # On-Call fields
        bigquery.SchemaField("UserId", "STRING"),
        bigquery.SchemaField("ScheduleId", "STRING"),
        bigquery.SchemaField("OnCallStart", "TIMESTAMP"),
        bigquery.SchemaField("OnCallEnd", "TIMESTAMP"),
        bigquery.SchemaField("OnCallLevel", "INTEGER"),
        
        # Alert fields
        bigquery.SchemaField("AlertStatus", "STRING"),
        bigquery.SchemaField("AlertBody", "STRING"),
        bigquery.SchemaField("AlertCreatedAt", "TIMESTAMP"),
        
        # Metadata
        bigquery.SchemaField("RawJson", "STRING"),
        bigquery.SchemaField("SyncTime", "TIMESTAMP"),
    ]

    table_ref = client.dataset(dataset_id).table(temp_table_id)
    table = bigquery.Table(table_ref, schema=schema)

    try:
        client.delete_table(table_ref, not_found_ok=True)
        client.create_table(table)
        logging.info(f"Created temp table {dataset_id}.{temp_table_id}")
        return True
    except GoogleAPIError as e:
        logging.error(f"Error creating temp table {dataset_id}.{temp_table_id}: {e}")
        return False

def delete_temp_table(client: bigquery.Client, dataset_id: str, temp_table_id: str) -> bool:
    """Delete temporary staging table."""
    table_ref = client.dataset(dataset_id).table(temp_table_id)
    try:
        client.delete_table(table_ref, not_found_ok=True)
        logging.info(f"Deleted temp table {dataset_id}.{temp_table_id}")
        return True
    except GoogleAPIError as e:
        logging.error(f"Error deleting temp table: {e}")
        return False

def insert_rows_with_retry(
    client: bigquery.Client,
    dataset_id: str,
    table_id: str,
    rows: List[Dict],
    retries: int = 3,
    delay: int = 5
) -> bool:
    """Insert rows into BigQuery table with retry logic."""
    if not rows:
        logging.info(f"No rows to insert into {dataset_id}.{table_id}")
        return True
    
    table_ref = client.dataset(dataset_id).table(table_id)
    
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(table_ref, rows)
            if errors:
                logging.error(f"Insert errors: {errors}")
                if attempt < retries - 1:
                    logging.info(f"Retrying in {delay} seconds... (attempt {attempt + 1}/{retries})")
                    time.sleep(delay)
                continue
            logging.info(f"Inserted {len(rows)} rows into {dataset_id}.{table_id}")
            return True
        except GoogleAPIError as e:
            logging.error(f"Error inserting rows (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    
    return False

@functions_framework.http
def pagerduty_sync(request):
    """HTTP Cloud Function: Sync PagerDuty data to BigQuery."""
    
    run_id = str(uuid.uuid4())
    pipeline_name = "PagerDuty"
    
    try:
        client = bigquery.Client()
        project_id = client.project
        dataset_id = "GSO"
        
        run_started = datetime.now(timezone.utc)
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="PagerDuty sync started",
            status="RUNNING",
            project=project_id,
            dataset=dataset_id
        )
        
        # Load PagerDuty token from Secret Manager
        try:
            pd_token = get_secret("pagerduty-api-token", project_id)
        except Exception as e:
            logging.error(f"Failed to retrieve PagerDuty API token from Secret Manager: {e}")
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Failed to retrieve PagerDuty API token",
                status="FAILED",
                error_code="NO_TOKEN",
                project=project_id,
                dataset=dataset_id
            )
            return {"status": "FAILED", "message": "Missing PagerDuty API token"}, 400
        
        logging.info("Starting PagerDuty data sync...")
        
        total_rows_merged = 0
        
        table_id = "PagerDuty"
        temp_table_id = "PagerDuty_temp"

        # Calculate 48-hour window for delta sync
        since = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        logging.info(f"Fetching data since {since} (48-hour delta sync)")

        endpoints = [
            ("incidents", "/incidents"),
            # ("alerts", "/alerts"),  # Skipped - requires different API scope
            ("oncalls", "/oncalls"),
            ("schedules", "/schedules"),
            ("services", "/services"),
            ("escalation_policies", "/escalation_policies"),
            ("users", "/users"),
            ("teams", "/teams"),
        ]

        all_rows: List[Dict[str, Any]] = []
        for entity_type, endpoint in endpoints:
            # Use delta sync for endpoints that support 'since' parameter
            # oncalls, escalation_policies, teams don't change often, so full sync is acceptable
            use_delta = entity_type in ["incidents", "services", "users", "schedules", "oncalls"]
            params = {"since": since} if use_delta else {}
            
            sync_type = "delta" if use_delta else "full"
            logging.info(f"Syncing {entity_type} ({sync_type})...")
            
            raw_data = pagerduty_request(endpoint, pd_token, params=params)
            if raw_data is None:
                logging.error(f"Failed to fetch {entity_type} from PagerDuty")
                continue

            logging.info(f"Fetched {len(raw_data)} {entity_type} from PagerDuty")
            for item in raw_data:
                row = build_entity_row(entity_type, item)
                if row:
                    all_rows.append(row)

        if not all_rows:
            logging.info("No PagerDuty data to sync")
            return {"status": "SUCCESS", "rows_merged": 0, "duration_seconds": 0}, 200

        if not create_or_replace_temp_table(client, dataset_id, temp_table_id):
            logging.error("Failed to create temp table")
            return {"status": "FAILED", "message": "Failed to create temp table"}, 500

        if not insert_rows_with_retry(client, dataset_id, temp_table_id, all_rows):
            logging.error("Failed to insert rows into temp table")
            delete_temp_table(client, dataset_id, temp_table_id)
            return {"status": "FAILED", "message": "Failed to insert temp rows"}, 500

        try:
            # Build MERGE query with all fields
            all_fields = [
                "EntityType", "EntityId", "ParentId", "Name", "Summary", "Status", "HtmlUrl",
                "CreatedAt", "UpdatedAt", "IncidentNumber", "Urgency", "Title", "Description",
                "ImpactedServices", "EscalationPolicyId", "FirstTriggeredAt", "LastStatusChangeAt",
                "LastStatusChangeBy", "FirstResolvedAt", "LastResolvedAt", "ServiceStatus",
                "ServiceDescription", "AutoResolveTimeout", "AcknowledgementTimeout",
                "DefaultEscalationPolicyId", "ServiceTeamSummaries", "ServiceIntegrationSummaries",
                "Email", "UserStatus", "AvatarUrl", "UserRole", "TimeZone", "UserTeamSummaries",
                "TeamDescription", "MemberSummaries", "ScheduleTimeZone", "ScheduleLayerSummaries",
                "OverrideSummaries", "FinalSchedule", "NumLayers", "RepeatEnabled",
                "EscalationRuleSummaries", "UserId", "ScheduleId", "OnCallStart", "OnCallEnd",
                "OnCallLevel", "AlertStatus", "AlertBody", "AlertCreatedAt", "RawJson", "SyncTime"
            ]
            
            # Build UPDATE SET clause (exclude EntityType, EntityId which are the key)
            update_pairs = [f"{field} = S.{field}" for field in all_fields if field not in ["EntityType", "EntityId"]]
            update_set = ",\n                    ".join(update_pairs)
            
            # Build INSERT columns and VALUES
            insert_columns = ", ".join(all_fields)
            insert_values = ", ".join([f"S.{field}" for field in all_fields])
            
            merge_query = f"""
                MERGE `{dataset_id}.{table_id}` T
                USING (
                    SELECT DISTINCT * EXCEPT(RowNum)
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY EntityType, EntityId ORDER BY SyncTime DESC) as RowNum
                        FROM `{dataset_id}.{temp_table_id}`
                    )
                    WHERE RowNum = 1
                ) S
                ON T.EntityType = S.EntityType AND T.EntityId = S.EntityId
                WHEN MATCHED THEN UPDATE SET
                    {update_set}
                WHEN NOT MATCHED THEN INSERT (
                    {insert_columns}
                ) VALUES (
                    {insert_values}
                )
            """
            job = client.query(merge_query)
            job.result()
            rows_merged = int(job.num_dml_affected_rows or 0)
            total_rows_merged += rows_merged
            logging.info(f"Merged {rows_merged} rows into {dataset_id}.{table_id}")
        except Exception as e:
            logging.error(f"Error merging temp table into final table: {e}")
        finally:
            delete_temp_table(client, dataset_id, temp_table_id)
        
        # Log success
        run_duration = (datetime.now(timezone.utc) - run_started).total_seconds()
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline finished",
            status="SUCCESS",
            window_start=run_started.isoformat(),
            window_end=datetime.now(timezone.utc).isoformat(),
            rows_merged=total_rows_merged,
            duration_seconds=run_duration,
            project=project_id,
            dataset=dataset_id
        )
        
        logging.info(f"PagerDuty sync completed in {run_duration:.2f}s. Merged {total_rows_merged} rows.")
        
        return {"status": "SUCCESS", "rows_merged": total_rows_merged, "duration_seconds": run_duration}, 200
        
    except Exception as e:
        logging.exception(f"Fatal error in PagerDuty sync: {e}")
        run_duration = (datetime.now(timezone.utc) - run_started).total_seconds() if 'run_started' in locals() else 0
        log_pipeline_run(
            client if 'client' in locals() else None,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="ERROR",
            message=f"Pipeline failed: {str(e)[:500]}",
            status="FAILED",
            error_code="FATAL_ERROR",
            duration_seconds=run_duration,
            project=project_id if 'project_id' in locals() else "pccw-internal-virt-agent-uat",
            dataset=dataset_id if 'dataset_id' in locals() else "GSO"
        )
        return {"status": "FAILED", "message": str(e)}, 500
