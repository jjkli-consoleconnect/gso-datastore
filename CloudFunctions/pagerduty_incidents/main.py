import functions_framework
import logging
import json
import requests
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set project ID before importing modules that need it
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "pccw-internal-virt-agent-uat"

from google.cloud import bigquery
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError

from logging_config import setup_root_logging
from secrets_manager import get_secret

# Setup logging
setup_root_logging()
logger = logging.getLogger(__name__)

# PagerDuty API config
PAGERDUTY_API_BASE = "https://api.pagerduty.com"
MAX_WORKERS = 5  # Concurrent detail endpoint calls
BATCH_SIZE = 100  # Incidents per list request

def pagerduty_request(
    endpoint: str,
    token: str,
    params: Dict[str, Any] = None,
    limit: int = 100,
    single_request: bool = False
) -> Optional[Dict[str, Any]]:
    """Make PagerDuty API request."""
    if not params:
        params = {}
    
    params["limit"] = limit
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
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"PagerDuty API error on {endpoint}: {e}")
        return None


def fetch_incidents_list(token: str, since: Optional[str] = None, statuses: List[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Fetch list of incidents."""
    params = {}
    if since:
        params["since"] = since
    if statuses:
        params["statuses[]"] = statuses
    
    offset = 0
    all_incidents = []
    
    while True:
        params["offset"] = offset
        data = pagerduty_request("/incidents", token, params, limit=BATCH_SIZE)
        
        if not data:
            return None
        
        incidents = data.get("incidents", [])
        if not incidents:
            break
        
        all_incidents.extend(incidents)
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
        logger.info(f"Fetched {len(all_incidents)} incidents so far...")
    
    logger.info(f"Total incidents fetched: {len(all_incidents)}")
    return all_incidents


def fetch_incident_detail(incident_id: str, token: str) -> Optional[Dict[str, Any]]:
    """Fetch complete incident details."""
    data = pagerduty_request(f"/incidents/{incident_id}", token, single_request=True)
    if data:
        return data.get("incident")
    return None


def fetch_incident_log_entries(incident_id: str, token: str, include_types: List[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Fetch incident log entries."""
    params = {}
    if include_types:
        params["include[]"] = include_types
    
    offset = 0
    all_entries = []
    
    while True:
        params["offset"] = offset
        data = pagerduty_request(f"/incidents/{incident_id}/log_entries", token, params, limit=BATCH_SIZE)
        
        if not data:
            return None
        
        entries = data.get("log_entries", [])
        if not entries:
            break
        
        all_entries.extend(entries)
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
    
    return all_entries


def enrich_incident_with_details(
    incident_summary: Dict[str, Any],
    incident_detail: Dict[str, Any],
    log_entries: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Merge incident data and extract key metrics."""
    # Build record with ONLY fields we defined in the schema
    record = {
        "SyncTime": datetime.now(timezone.utc).isoformat(),
        "id": incident_detail.get("id"),
        "type": incident_detail.get("type"),
        "incident_number": incident_detail.get("incident_number"),
        "title": incident_detail.get("title"),
        "description": incident_detail.get("description"),
        "created_at": incident_detail.get("created_at"),
        "updated_at": incident_detail.get("updated_at"),
        "status": incident_detail.get("status"),
        "resolved_at": incident_detail.get("resolved_at"),
        "FirstResolvedAt": incident_detail.get("first_resolved_at"),
        "LastResolvedAt": incident_detail.get("last_resolved_at"),
        "incident_key": incident_detail.get("incident_key"),
        "urgency": incident_detail.get("urgency"),
        "assigned_via": incident_detail.get("assigned_via"),
        "alert_counts": str(incident_detail.get("alert_counts")) if incident_detail.get("alert_counts") else None,
        "last_status_update_at": incident_detail.get("last_status_update_at"),
        "last_assigned_at": incident_detail.get("last_assigned_at"),
        "first_assigned_at": incident_detail.get("first_assigned_at"),
        "html_url": incident_detail.get("html_url"),
        "self": incident_detail.get("self"),
    }
    
    # Resolution timestamps
    record["FirstResolvedAt"] = incident_detail.get("first_resolved_at")
    record["LastResolvedAt"] = incident_detail.get("last_resolved_at")
    
    # Extract assignment summaries
    assignments = incident_detail.get("assignments", [])
    record["AssignmentSummaries"] = [
        f"{a.get('assignee', {}).get('summary', 'Unknown')} - {a.get('at', '')}"
        for a in assignments
    ]
    
    # Extract acknowledgement summaries
    acknowledgements = incident_detail.get("acknowledgements", [])
    record["AcknowledgementSummaries"] = [
        f"{a.get('acknowledger', {}).get('summary', 'Unknown')} - {a.get('at', '')}"
        for a in acknowledgements
    ]
    
    # Extract team summaries
    teams = incident_detail.get("teams", [])
    record["TeamSummaries"] = [t.get("summary") for t in teams if t.get("summary")]
    
    # Priority info
    priority = incident_detail.get("priority", {})
    record["PriorityName"] = priority.get("summary") if priority else None
    record["PriorityId"] = priority.get("id") if priority else None
    
    # Incident type
    incident_type = incident_detail.get("incident_type", {})
    record["IncidentTypeName"] = incident_type.get("summary") if incident_type else None
    record["IncidentTypeId"] = incident_type.get("id") if incident_type else None
    
    # Service info
    service = incident_detail.get("service", {})
    record["ServiceId"] = service.get("id")
    record["ServiceSummary"] = service.get("summary")
    
    # Escalation policy
    escalation_policy = incident_detail.get("escalation_policy", {})
    record["EscalationPolicyId"] = escalation_policy.get("id")
    record["EscalationPolicySummary"] = escalation_policy.get("summary")
    
    # Conference bridge
    conference_bridge = incident_detail.get("conference_bridge", {})
    if conference_bridge:
        record["ConferenceBridgeConferenceNumber"] = conference_bridge.get("conference_number")
        record["ConferenceBridgeConferenceURL"] = conference_bridge.get("conference_url")
    
    # Impact
    impact = incident_detail.get("impact", {})
    if impact:
        record["ImpactType"] = impact.get("type")
    
    # Log entries metrics
    if log_entries:
        record["TotalLogEntries"] = len(log_entries)
        resolution_events = [e for e in log_entries if e.get("type") == "resolve_log_entry"]
        if resolution_events:
            record["FirstResolutionEvent"] = resolution_events[0].get("created_at")
            record["LastResolutionEvent"] = resolution_events[-1].get("created_at")
    
    return record


def create_bigquery_schema() -> List[bigquery.SchemaField]:
    """Define BigQuery schema."""
    schema = [
        bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("incident_number", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("status", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("resolved_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("FirstResolvedAt", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("LastResolvedAt", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("incident_key", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("urgency", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("assigned_via", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("alert_counts", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ServiceId", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ServiceSummary", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("PriorityName", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("PriorityId", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("IncidentTypeName", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("IncidentTypeId", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("EscalationPolicyId", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("EscalationPolicySummary", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ConferenceBridgeConferenceNumber", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ConferenceBridgeConferenceURL", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ImpactType", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("AssignmentSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("AcknowledgementSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("TeamSummaries", "STRING", mode="REPEATED"),
        bigquery.SchemaField("last_status_update_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("last_assigned_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("first_assigned_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("TotalLogEntries", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("FirstResolutionEvent", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("LastResolutionEvent", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("html_url", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("self", "STRING", mode="NULLABLE"),
    ]
    return schema


def create_or_get_table(dataset_id: str, table_id: str, project_id: str, schema: List[bigquery.SchemaField]) -> bigquery.Table:
    """Create BigQuery table if it doesn't exist."""
    client = bigquery.Client(project=project_id)
    table_id_full = f"{project_id}.{dataset_id}.{table_id}"
    
    try:
        # Try to get the table
        table = client.get_table(table_id_full)
        
        # Check if schema matches - if not, recreate
        existing_schema_fields = {f.name for f in table.schema}
        expected_schema_fields = {f.name for f in schema}
        
        if existing_schema_fields != expected_schema_fields:
            logger.warning(f"Schema mismatch. Existing: {len(existing_schema_fields)}, Expected: {len(expected_schema_fields)}")
            logger.warning(f"Missing fields: {expected_schema_fields - existing_schema_fields}")
            # Delete and recreate
            client.delete_table(table_id_full, not_found_ok=True)
            time.sleep(0.5)
            table = bigquery.Table(table_id_full, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="SyncTime"
            )
            table.clustering_fields = ["EscalationPolicySummary", "resolved_at", "created_at"]
            table = client.create_table(table)
            logger.info(f"Recreated table {table_id_full} with corrected schema ({len(schema)} fields)")
            time.sleep(2)
        else:
            logger.info(f"Table {table_id_full} exists with correct schema ({len(table.schema)} fields)")
        
        return table
    except NotFound:
        table = bigquery.Table(table_id_full, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="SyncTime"
        )
        table.clustering_fields = ["EscalationPolicySummary", "resolved_at", "created_at"]
        table = client.create_table(table)
        logger.info(f"Created table {table_id_full} with schema ({len(schema)} fields)")
        time.sleep(2)
        return table


def insert_incidents_to_bigquery(
    incidents: List[Dict[str, Any]],
    table: bigquery.Table
) -> bool:
    """Insert incidents into BigQuery using temp table + MERGE pattern."""
    if not incidents:
        logger.warning("No incidents to insert")
        return True
    
    client = bigquery.Client(project=table.project)
    
    try:
        table_id_full = f"{table.project}.{table.dataset_id}.{table.table_id}"
        temp_table_id = f"{table.project}.{table.dataset_id}.{table.table_id}_temp"
        
        logger.info(f"Starting MERGE workflow for {len(incidents)} incidents to {table_id_full}")
        
        # Verify main table exists and get schema
        table = client.get_table(table)
        logger.info(f"Main table schema has {len(table.schema)} fields")
        
        # Step 1: Create temporary table with same schema
        temp_table = bigquery.Table(temp_table_id, schema=table.schema)
        temp_table.time_partitioning = table.time_partitioning
        temp_table.clustering_fields = table.clustering_fields
        
        # Delete temp table if it exists from previous run
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
            logger.info(f"Cleaned up old temp table")
        except Exception as e:
            logger.warning(f"Temp cleanup warning: {e}")
        
        # Create fresh temp table
        temp_table = client.create_table(temp_table)
        logger.info(f"Created temp table: {temp_table_id}")
        time.sleep(2)  # Allow propagation
        
        # Step 2: Insert all new data into temp table
        errors = client.insert_rows_json(temp_table, incidents, skip_invalid_rows=True)
        
        if errors:
            logger.warning(f"Temp insert had {len(errors)} rows skipped")
            for error in errors[:3]:
                logger.error(f"  Temp insert error: {error}")
        
        logger.info(f"Inserted {len(incidents)} incidents into temp table")
        time.sleep(2)  # Allow data to settle
        
        # Step 3: MERGE from temp to main table
        merge_sql = f"""
        MERGE `{table_id_full}` T
        USING `{temp_table_id}` S
        ON T.incident_number = S.incident_number
        WHEN MATCHED THEN
            UPDATE SET
                SyncTime = S.SyncTime,
                id = S.id,
                type = S.type,
                title = S.title,
                description = S.description,
                created_at = S.created_at,
                updated_at = S.updated_at,
                status = S.status,
                resolved_at = S.resolved_at,
                FirstResolvedAt = S.FirstResolvedAt,
                LastResolvedAt = S.LastResolvedAt,
                incident_key = S.incident_key,
                urgency = S.urgency,
                assigned_via = S.assigned_via,
                alert_counts = S.alert_counts,
                ServiceId = S.ServiceId,
                ServiceSummary = S.ServiceSummary,
                PriorityName = S.PriorityName,
                PriorityId = S.PriorityId,
                IncidentTypeName = S.IncidentTypeName,
                IncidentTypeId = S.IncidentTypeId,
                EscalationPolicyId = S.EscalationPolicyId,
                EscalationPolicySummary = S.EscalationPolicySummary,
                ConferenceBridgeConferenceNumber = S.ConferenceBridgeConferenceNumber,
                ConferenceBridgeConferenceURL = S.ConferenceBridgeConferenceURL,
                ImpactType = S.ImpactType,
                AssignmentSummaries = S.AssignmentSummaries,
                AcknowledgementSummaries = S.AcknowledgementSummaries,
                TeamSummaries = S.TeamSummaries,
                last_status_update_at = S.last_status_update_at,
                last_assigned_at = S.last_assigned_at,
                first_assigned_at = S.first_assigned_at,
                TotalLogEntries = S.TotalLogEntries,
                FirstResolutionEvent = S.FirstResolutionEvent,
                LastResolutionEvent = S.LastResolutionEvent,
                html_url = S.html_url,
                self = S.self
        WHEN NOT MATCHED THEN
            INSERT (
                SyncTime, id, type, incident_number, title, description,
                created_at, updated_at, status, resolved_at, FirstResolvedAt, LastResolvedAt,
                incident_key, urgency, assigned_via, alert_counts,
                ServiceId, ServiceSummary, PriorityName, PriorityId,
                IncidentTypeName, IncidentTypeId, EscalationPolicyId, EscalationPolicySummary,
                ConferenceBridgeConferenceNumber, ConferenceBridgeConferenceURL, ImpactType,
                AssignmentSummaries, AcknowledgementSummaries, TeamSummaries,
                last_status_update_at, last_assigned_at, first_assigned_at,
                TotalLogEntries, FirstResolutionEvent, LastResolutionEvent,
                html_url, self
            )
            VALUES (
                S.SyncTime, S.id, S.type, S.incident_number, S.title, S.description,
                S.created_at, S.updated_at, S.status, S.resolved_at, S.FirstResolvedAt, S.LastResolvedAt,
                S.incident_key, S.urgency, S.assigned_via, S.alert_counts,
                S.ServiceId, S.ServiceSummary, S.PriorityName, S.PriorityId,
                S.IncidentTypeName, S.IncidentTypeId, S.EscalationPolicyId, S.EscalationPolicySummary,
                S.ConferenceBridgeConferenceNumber, S.ConferenceBridgeConferenceURL, S.ImpactType,
                S.AssignmentSummaries, S.AcknowledgementSummaries, S.TeamSummaries,
                S.last_status_update_at, S.last_assigned_at, S.first_assigned_at,
                S.TotalLogEntries, S.FirstResolutionEvent, S.LastResolutionEvent,
                S.html_url, S.self
            )
        """
        
        logger.info("Executing MERGE statement...")
        merge_job = client.query(merge_sql)
        merge_result = merge_job.result()
        
        logger.info(f"MERGE completed successfully")
        
        # Step 4: Clean up temp table
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
            logger.info(f"Deleted temp table")
        except Exception as e:
            logger.warning(f"Temp table cleanup warning: {e}")
        
        logger.info(f"Successfully merged {len(incidents)} incidents")
        return True
        
    except Exception as e:
        logger.error(f"MERGE error: {e}", exc_info=True)
        # Try to clean up temp table on error
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
        except:
            pass
        return False


def fetch_incident_details_parallel(
    incident_summaries: List[Dict[str, Any]],
    token: str,
    fetch_log_entries: bool = False
) -> List[Dict[str, Any]]:
    """Fetch incident details in parallel."""
    enriched_incidents = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        
        for incident_summary in incident_summaries:
            incident_id = incident_summary.get("id")
            future = executor.submit(fetch_incident_detail, incident_id, token)
            futures[future] = incident_id
        
        completed = 0
        for future in as_completed(futures):
            incident_id = futures[future]
            incident_detail = future.result()
            
            if incident_detail:
                log_entries = None
                if fetch_log_entries:
                    log_entries = fetch_incident_log_entries(incident_id, token)
                
                enriched = enrich_incident_with_details(
                    incident_summary,
                    incident_detail,
                    log_entries
                )
                enriched_incidents.append(enriched)
            
            completed += 1
            if completed % 10 == 0:
                logger.info(f"Enriched {completed}/{len(incident_summaries)} incidents")
    
    return enriched_incidents


@functions_framework.http
def sync_incidents(request):
    """HTTP-triggered Cloud Function to sync PagerDuty incidents."""
    try:
        project_id = "pccw-internal-virt-agent-uat"
        dataset_id = "GSO"
        table_id = "PagerDutyIncidents"
        
        token = get_secret("pagerduty-api-token", project_id=project_id)
        if not token:
            return {"error": "Failed to retrieve API token"}, 500
        
        delta = request.args.get("delta", "true").lower() == "true"
        fetch_log_entries = request.args.get("fetch_log_entries", "false").lower() == "true"
        statuses_param = request.args.get("statuses", "triggered,acknowledged,resolved")
        statuses = [s.strip() for s in statuses_param.split(",")]
        
        logger.info(f"Starting incident sync - Delta: {delta}, Log entries: {fetch_log_entries}")
        
        since = None
        if delta:
            since = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            logger.info(f"Delta sync since: {since}")
        
        schema = create_bigquery_schema()
        table = create_or_get_table(dataset_id, table_id, project_id, schema)
        logger.info(f"Using table: {table.project}.{table.dataset_id}.{table.table_id}")
        
        incident_summaries = fetch_incidents_list(token, since, statuses)
        if not incident_summaries:
            return {"error": "Failed to fetch incidents"}, 500
        
        logger.info(f"Fetched {len(incident_summaries)} incident summaries")
        
        enriched_incidents = fetch_incident_details_parallel(
            incident_summaries,
            token,
            fetch_log_entries
        )
        
        logger.info(f"Enriched {len(enriched_incidents)} incidents")
        
        success = insert_incidents_to_bigquery(
            enriched_incidents,
            table
        )
        
        if not success:
            return {"error": "Failed to insert incidents into BigQuery"}, 500
        
        logger.info(f"Sync completed: {len(enriched_incidents)} incidents")
        
        return {
            "status": "success",
            "incidents_synced": len(enriched_incidents),
            "sync_type": "delta" if delta else "full",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, 200
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return {"error": str(e)}, 500
