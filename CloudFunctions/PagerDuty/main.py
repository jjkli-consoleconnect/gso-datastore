import functions_framework
import logging
import json
import uuid
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.cloud import bigquery, secretmanager
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError

from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

# Setup logging
setup_root_logging()

# PagerDuty API config
PAGERDUTY_API_BASE = "https://api.pagerduty.com"

def get_secret(secret_id: str, project_id: str = "pccw-internal-virt-agent-uat") -> str:
    """Retrieve secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

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

def flatten_incident(incident: Dict) -> Dict:
    """Flatten PagerDuty incident object for BigQuery."""
    urgency = incident.get("urgency", "")
    assignees = incident.get("assignments", [])
    assignee_ids = [a.get("assignee", {}).get("id") for a in assignees if a.get("assignee")]
    assignee_names = [a.get("assignee", {}).get("summary") for a in assignees if a.get("assignee")]
    
    return {
        "incident_id": incident.get("id"),
        "incident_number": incident.get("incident_number"),
        "title": incident.get("title"),
        "description": incident.get("description"),
        "created_at": incident.get("created_at"),
        "status": incident.get("status"),
        "pending_actions": str(incident.get("pending_actions", [])),
        "urgency": urgency,
        "incident_key": incident.get("incident_key"),
        "service_id": incident.get("service", {}).get("id"),
        "service_name": incident.get("service", {}).get("summary"),
        "assigned_via": incident.get("assigned_via"),
        "assignments_json": json.dumps(assignee_ids),
        "assignee_names": ",".join(assignee_names) if assignee_names else None,
        "escalation_policy_id": incident.get("escalation_policy", {}).get("id"),
        "first_trigger_log_entry_id": incident.get("first_trigger_log_entry", {}).get("id"),
        "escalation_count": len(incident.get("escalation_policy", {}).get("escalation_rules", [])),
        "last_status_change_at": incident.get("last_status_change_at"),
        "last_status_change_by_id": incident.get("last_status_change_by", {}).get("id"),
        "first_assignment_at": assignees[0].get("at") if assignees else None,
        "sync_time": datetime.now(timezone.utc).isoformat(),
    }

def flatten_oncall(on_call: Dict) -> Dict:
    """Flatten PagerDuty on-call object for BigQuery."""
    return {
        "on_call_id": f"{on_call.get('schedule', {}).get('id')}_{on_call.get('user', {}).get('id')}_{on_call.get('start')}",
        "user_id": on_call.get("user", {}).get("id"),
        "user_email": on_call.get("user", {}).get("email"),
        "user_summary": on_call.get("user", {}).get("summary"),
        "schedule_id": on_call.get("schedule", {}).get("id"),
        "schedule_name": on_call.get("schedule", {}).get("summary"),
        "escalation_level": on_call.get("escalation_level"),
        "escalation_policy_id": on_call.get("escalation_policy", {}).get("id"),
        "start": on_call.get("start"),
        "end": on_call.get("end"),
        "sync_time": datetime.now(timezone.utc).isoformat(),
    }

def flatten_service(service: Dict) -> Dict:
    """Flatten PagerDuty service object for BigQuery."""
    return {
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "service_summary": service.get("summary"),
        "status": service.get("status"),
        "description": service.get("description"),
        "created_at": service.get("created_at"),
        "escalation_policy_id": service.get("escalation_policy", {}).get("id"),
        "escalation_policy_name": service.get("escalation_policy", {}).get("summary"),
        "teams_json": json.dumps([t.get("id") for t in service.get("teams", [])]),
        "sync_time": datetime.now(timezone.utc).isoformat(),
    }

def flatten_escalation_policy(policy: Dict) -> Dict:
    """Flatten PagerDuty escalation policy object for BigQuery."""
    rules = policy.get("escalation_rules", [])
    rule_count = len(rules)
    
    return {
        "policy_id": policy.get("id"),
        "policy_name": policy.get("name"),
        "policy_summary": policy.get("summary"),
        "num_escalation_rules": rule_count,
        "repeat_enabled": policy.get("repeat_enabled", False),
        "escalation_rules_json": json.dumps(rules),
        "sync_time": datetime.now(timezone.utc).isoformat(),
    }

def get_primary_key(data_type: str) -> str:
    """Get the primary key for each data type."""
    keys = {
        "incidents": "incident_id",
        "oncalls": "on_call_id",
        "services": "service_id",
        "escalation_policies": "policy_id",
    }
    return keys.get(data_type, "id")

def create_or_replace_temp_table(client: bigquery.Client, dataset_id: str, temp_table_id: str, table_type: str) -> bool:
    """Create or replace a temporary staging table."""
    
    schemas = {
        "incidents": [
            bigquery.SchemaField("incident_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("incident_number", "INTEGER"),
            bigquery.SchemaField("title", "STRING"),
            bigquery.SchemaField("description", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("pending_actions", "STRING"),
            bigquery.SchemaField("urgency", "STRING"),
            bigquery.SchemaField("incident_key", "STRING"),
            bigquery.SchemaField("service_id", "STRING"),
            bigquery.SchemaField("service_name", "STRING"),
            bigquery.SchemaField("assigned_via", "STRING"),
            bigquery.SchemaField("assignments_json", "STRING"),
            bigquery.SchemaField("assignee_names", "STRING"),
            bigquery.SchemaField("escalation_policy_id", "STRING"),
            bigquery.SchemaField("first_trigger_log_entry_id", "STRING"),
            bigquery.SchemaField("escalation_count", "INTEGER"),
            bigquery.SchemaField("last_status_change_at", "TIMESTAMP"),
            bigquery.SchemaField("last_status_change_by_id", "STRING"),
            bigquery.SchemaField("first_assignment_at", "TIMESTAMP"),
            bigquery.SchemaField("sync_time", "TIMESTAMP"),
        ],
        "oncalls": [
            bigquery.SchemaField("on_call_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("user_id", "STRING"),
            bigquery.SchemaField("user_email", "STRING"),
            bigquery.SchemaField("user_summary", "STRING"),
            bigquery.SchemaField("schedule_id", "STRING"),
            bigquery.SchemaField("schedule_name", "STRING"),
            bigquery.SchemaField("escalation_level", "INTEGER"),
            bigquery.SchemaField("escalation_policy_id", "STRING"),
            bigquery.SchemaField("start", "TIMESTAMP"),
            bigquery.SchemaField("end", "TIMESTAMP"),
            bigquery.SchemaField("sync_time", "TIMESTAMP"),
        ],
        "services": [
            bigquery.SchemaField("service_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("service_name", "STRING"),
            bigquery.SchemaField("service_summary", "STRING"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("description", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
            bigquery.SchemaField("escalation_policy_id", "STRING"),
            bigquery.SchemaField("escalation_policy_name", "STRING"),
            bigquery.SchemaField("teams_json", "STRING"),
            bigquery.SchemaField("sync_time", "TIMESTAMP"),
        ],
        "escalation_policies": [
            bigquery.SchemaField("policy_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("policy_name", "STRING"),
            bigquery.SchemaField("policy_summary", "STRING"),
            bigquery.SchemaField("num_escalation_rules", "INTEGER"),
            bigquery.SchemaField("repeat_enabled", "BOOLEAN"),
            bigquery.SchemaField("escalation_rules_json", "STRING"),
            bigquery.SchemaField("sync_time", "TIMESTAMP"),
        ],
    }
    
    schema = schemas.get(table_type, [])
    if not schema:
        logging.error(f"Unknown table type: {table_type}")
        return False
    
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
            errors = client.insert_rows_json(table_ref, [json.dumps(row) for row in rows])
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
    pipeline_name = "pagerduty"
    
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
        
        # Sync each data type
        for data_type, endpoint, flatten_func in [
            ("incidents", "/incidents", flatten_incident),
            ("oncalls", "/oncalls", flatten_oncall),
            ("services", "/services", flatten_service),
            ("escalation_policies", "/escalation_policies", flatten_escalation_policy),
        ]:
            logging.info(f"Syncing {data_type}...")
            
            table_id = f"PagerDuty_{data_type.title().replace('_', '')}"
            temp_table_id = f"{table_id}_temp"
            
            # Fetch data from PagerDuty
            raw_data = pagerduty_request(endpoint, pd_token)
            if raw_data is None:
                logging.error(f"Failed to fetch {data_type} from PagerDuty")
                continue
            
            logging.info(f"Fetched {len(raw_data)} {data_type} from PagerDuty")
            
            if not raw_data:
                logging.info(f"No {data_type} to sync")
                continue
            
            # Flatten data for BigQuery
            rows = [flatten_func(item) for item in raw_data]
            
            # Create temp table
            if not create_or_replace_temp_table(client, dataset_id, temp_table_id, data_type):
                logging.error(f"Failed to create temp table for {data_type}")
                continue
            
            # Insert into temp table
            if not insert_rows_with_retry(client, dataset_id, temp_table_id, rows):
                logging.error(f"Failed to insert {data_type} into temp table")
                delete_temp_table(client, dataset_id, temp_table_id)
                continue
            
            # Merge temp table into final table
            try:
                pk = get_primary_key(data_type)
                
                # Build dynamic WHEN MATCHED clause based on data type
                if data_type == "incidents":
                    set_clause = """
                        incident_number = S.incident_number,
                        title = S.title,
                        description = S.description,
                        created_at = S.created_at,
                        status = S.status,
                        pending_actions = S.pending_actions,
                        urgency = S.urgency,
                        incident_key = S.incident_key,
                        service_id = S.service_id,
                        service_name = S.service_name,
                        assigned_via = S.assigned_via,
                        assignments_json = S.assignments_json,
                        assignee_names = S.assignee_names,
                        escalation_policy_id = S.escalation_policy_id,
                        first_trigger_log_entry_id = S.first_trigger_log_entry_id,
                        escalation_count = S.escalation_count,
                        last_status_change_at = S.last_status_change_at,
                        last_status_change_by_id = S.last_status_change_by_id,
                        first_assignment_at = S.first_assignment_at,
                        sync_time = S.sync_time
                    """
                elif data_type == "oncalls":
                    set_clause = """
                        user_id = S.user_id,
                        user_email = S.user_email,
                        user_summary = S.user_summary,
                        schedule_id = S.schedule_id,
                        schedule_name = S.schedule_name,
                        escalation_level = S.escalation_level,
                        escalation_policy_id = S.escalation_policy_id,
                        start = S.start,
                        end = S.end,
                        sync_time = S.sync_time
                    """
                elif data_type == "services":
                    set_clause = """
                        service_name = S.service_name,
                        service_summary = S.service_summary,
                        status = S.status,
                        description = S.description,
                        created_at = S.created_at,
                        escalation_policy_id = S.escalation_policy_id,
                        escalation_policy_name = S.escalation_policy_name,
                        teams_json = S.teams_json,
                        sync_time = S.sync_time
                    """
                else:  # escalation_policies
                    set_clause = """
                        policy_name = S.policy_name,
                        policy_summary = S.policy_summary,
                        num_escalation_rules = S.num_escalation_rules,
                        repeat_enabled = S.repeat_enabled,
                        escalation_rules_json = S.escalation_rules_json,
                        sync_time = S.sync_time
                    """
                
                merge_query = f"""
                    MERGE `{dataset_id}.{table_id}` T
                    USING (
                        SELECT * FROM `{dataset_id}.{temp_table_id}`
                    ) S
                    ON T.{pk} = S.{pk}
                    WHEN MATCHED THEN
                        UPDATE SET
                            {set_clause}
                    WHEN NOT MATCHED THEN
                        INSERT *
                        VALUES (S.*)
                """
                
                job = client.query(merge_query)
                job.result()
                rows_merged = job.total_rows
                total_rows_merged += rows_merged
                logging.info(f"Merged {rows_merged} {data_type} into {dataset_id}.{table_id}")
                
            except Exception as e:
                logging.error(f"Error merging {data_type}: {e}")
            
            finally:
                delete_temp_table(client, dataset_id, temp_table_id)
        
        # Log success
        run_duration = (datetime.now(timezone.utc) - run_started).total_seconds()
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message=f"PagerDuty sync completed successfully. Merged {total_rows_merged} rows total.",
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
            message=f"PagerDuty sync failed: {str(e)[:500]}",
            status="FAILED",
            error_code="FATAL_ERROR",
            duration_seconds=run_duration,
            project=project_id if 'project_id' in locals() else "pccw-internal-virt-agent-uat",
            dataset=dataset_id if 'dataset_id' in locals() else "GSO"
        )
        return {"status": "FAILED", "message": str(e)}, 500
