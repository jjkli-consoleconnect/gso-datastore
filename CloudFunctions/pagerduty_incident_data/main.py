import functions_framework
import logging
import json
import requests
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set project ID before importing modules that need it
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "pccw-internal-virt-agent-uat"

from google.cloud import bigquery
from google.api_core.exceptions import Conflict, NotFound, GoogleAPIError

from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run
from secrets_manager import get_secret

# Setup logging
setup_root_logging()
logger = logging.getLogger(__name__)

# PagerDuty API config
PAGERDUTY_API_BASE = "https://api.pagerduty.com"
MAX_WORKERS = 5
BATCH_SIZE = 100
HKT = timezone(timedelta(hours=8))
LOG_TYPES = [
    "incident.triggered",
    "incident.acknowledged",
    "incident.resolved",
    "incident.auto_resolved",
    "incident.escalated",
    "incident.assignment_escalated",
    "incident.responder.added",
    "incident.reassigned",
    "incident.delegated"
]

BQ_FIELDS = [
    "incident_id",
    "incident_number",
    "incident_type",
    "title",
    "description",
    "status",
    "urgency",
    "priority",
    "service_id",
    "service_name",
    "escalation_policy_id",
    "escalation_policy_name",
    "created_at",
    "created_at_hkt",
    "first_trigger_time",
    "acknowledgement_time",
    "acknowledged_by",
    "resolved_at",
    "resolved_by",
    "auto_resolved",
    "last_status_update_at",
    "incident_key",
    "responders_display",
    "tta_seconds",
    "ttr_seconds",
    "response_effort_seconds",
    "escalations_count",
    "assignees_json",
    "responders",
    "responder_metrics",
    "service_performance",
    "jj_test_custom_field",
    "jira_issue",
    "custom_fields_json",
    "log_entries",
    "html_url",
    "sync_time"
]


def parse_pd_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse PagerDuty ISO timestamp to datetime."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def to_hkt_datetime(value: Optional[str]) -> Optional[datetime]:
    """Convert PagerDuty timestamp to HKT (UTC+8) datetime."""
    ts = parse_pd_timestamp(value)
    if not ts:
        return None
    return ts.astimezone(HKT).replace(tzinfo=None)


def normalize_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def extract_custom_fields(custom_fields: Optional[List[Dict[str, Any]]]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    for field in custom_fields or []:
        name = field.get("name") or field.get("summary")
        if not name:
            continue
        result[name] = normalize_json(field.get("value"))
    return result


def convert_datetimes_to_iso(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO format strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, bool):
        # Handle bool before int since bool is a subclass of int in Python
        return obj
    elif isinstance(obj, dict):
        return {k: convert_datetimes_to_iso(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_datetimes_to_iso(v) for v in obj]
    elif obj is None:
        return None
    else:
        return obj


def log_entry_actor_summary(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not entry:
        return None
    for key in ("agent", "user", "assignee", "responder"):
        actor = entry.get(key)
        if isinstance(actor, dict):
            return actor.get("summary") or actor.get("name") or actor.get("email")
    return None


def first_log_entry_time(log_entries: List[Dict[str, Any]], types: List[str]) -> Optional[datetime]:
    # Map API filter types to actual returned types
    type_map = {
        "incident.triggered": "trigger_log_entry",
        "incident.acknowledged": "acknowledge_log_entry",
        "incident.resolved": "resolve_log_entry",
        "incident.auto_resolved": "resolve_log_entry",
        "incident.escalated": "escalate_log_entry",
        "incident.assignment_escalated": "escalate_log_entry",
        "incident.responder.added": "responder.added_log_entry",
        "incident.reassigned": "reassign_log_entry",
        "incident.delegated": "delegate_log_entry"
    }
    actual_types = [type_map.get(t, t) for t in types]
    
    timestamps = [
        parse_pd_timestamp(entry.get("created_at"))
        for entry in log_entries
        if entry.get("type") in actual_types
    ]
    timestamps = [ts for ts in timestamps if ts]
    return min(timestamps) if timestamps else None


def last_log_entry(log_entries: List[Dict[str, Any]], types: List[str]) -> Optional[Dict[str, Any]]:
    # Map API filter types to actual returned types
    type_map = {
        "incident.triggered": "trigger_log_entry",
        "incident.acknowledged": "acknowledge_log_entry",
        "incident.resolved": "resolve_log_entry",
        "incident.auto_resolved": "resolve_log_entry",
        "incident.escalated": "escalate_log_entry",
        "incident.assignment_escalated": "escalate_log_entry",
        "incident.responder.added": "responder.added_log_entry",
        "incident.reassigned": "reassign_log_entry",
        "incident.delegated": "delegate_log_entry"
    }
    actual_types = [type_map.get(t, t) for t in types]
    
    filtered = [entry for entry in log_entries if entry.get("type") in actual_types]
    if not filtered:
        return None
    filtered.sort(key=lambda e: parse_pd_timestamp(e.get("created_at")) or datetime.min)
    return filtered[-1]


def build_log_entry_record(entry: Dict[str, Any]) -> Dict[str, Any]:
    actor = None
    actor_type = None
    actor_id = None
    for key in ("agent", "user", "assignee", "responder"):
        candidate = entry.get(key)
        if isinstance(candidate, dict):
            actor = candidate
            actor_type = candidate.get("type")
            actor_id = candidate.get("id")
            break
    return {
        "entry_type": entry.get("type"),
        "created_at": parse_pd_timestamp(entry.get("created_at")),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "actor_summary": actor.get("summary") if actor else None
    }


def extract_assignees(assignments: List[Dict[str, Any]]) -> Optional[str]:
    """Extract assignee names from assignment objects. Returns JSON string."""
    if not assignments:
        return None
    try:
        assignee_names = []
        for assignment in assignments:
            if "assignee" in assignment and assignment["assignee"]:
                assignee = assignment["assignee"]
                name = assignee.get("summary") or assignee.get("name") or assignee.get("email")
                if name:
                    assignee_names.append(name)
        if assignee_names:
            return json.dumps(assignee_names, ensure_ascii=True)
    except Exception as e:
        logger.warning(f"Error extracting assignees: {e}")
    return None


def pagerduty_request(
    endpoint: str,
    token: str,
    params: Dict[str, Any] = None,
    limit: int = 100
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
    
    logger.info(f"Calling PagerDuty {endpoint} with params: {list(params.keys())}")
    
    try:
        response = requests.get(
            f"{PAGERDUTY_API_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=30
        )
        logger.info(f"PagerDuty {endpoint} response: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        logger.info(f"PagerDuty {endpoint} response keys: {list(data.keys())}")
        return data
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = e.response.json() if e.response.text else e.response.text
        except:
            error_detail = e.response.text[:500]
        logger.error(f"PagerDuty API HTTP {e.response.status_code} on {endpoint}: {error_detail}")
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f"PagerDuty API timeout on {endpoint} (30s): {e}")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"PagerDuty API connection error on {endpoint}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"PagerDuty API error on {endpoint}: {type(e).__name__}: {str(e)[:500]}")
        return None


def fetch_incidents_paginated(
    token: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    statuses: List[str] = None,
    include_params: List[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """Fetch incidents list with pagination."""
    params = {
        "include[]": include_params or ["services", "escalation_policies", "assignees", "custom_fields"],
        "sort_by": "created_at:desc"
    }
    
    if since:
        params["since"] = since
    if until:
        params["until"] = until
    if statuses:
        params["statuses[]"] = statuses
    
    all_incidents = []
    offset = 0
    
    while True:
        params["offset"] = offset
        params["limit"] = BATCH_SIZE
        
        logger.info(f"Fetching incidents batch: offset={offset}, limit={BATCH_SIZE}")
        data = pagerduty_request("/incidents", token, params, limit=BATCH_SIZE)
        
        if data is None:
            logger.error("Failed to fetch incidents")
            return None
        
        incidents = data.get("incidents", [])
        if not incidents:
            logger.info(f"No more incidents to fetch (total: {len(all_incidents)})")
            break
        
        all_incidents.extend(incidents)
        logger.info(f"Fetched {len(incidents)} incidents (total: {len(all_incidents)})")
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
        time.sleep(0.5)  # Rate limiting
    
    return all_incidents


def fetch_services_dict(token: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """Fetch all services and return as dict keyed by service ID."""
    params = {
        "include[]": ["escalation_policies"]
    }
    
    all_services = {}
    offset = 0
    
    while True:
        params["offset"] = offset
        params["limit"] = BATCH_SIZE
        
        data = pagerduty_request("/services", token, params, limit=BATCH_SIZE)
        
        if data is None:
            logger.error("Failed to fetch services")
            return None
        
        services = data.get("services", [])
        if not services:
            logger.info(f"No more services to fetch (total: {len(all_services)})")
            break
        
        for service in services:
            all_services[service.get("id")] = service
        
        logger.info(f"Fetched {len(services)} services (total: {len(all_services)})")
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
        time.sleep(0.5)
    
    return all_services


def fetch_users_dict(token: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """Fetch all users and return as dict keyed by user ID."""
    params = {
        "include[]": ["teams"]
    }
    
    all_users = {}
    offset = 0
    
    while True:
        params["offset"] = offset
        params["limit"] = BATCH_SIZE
        
        data = pagerduty_request("/users", token, params, limit=BATCH_SIZE)
        
        if data is None:
            logger.error("Failed to fetch users")
            return None
        
        users = data.get("users", [])
        if not users:
            logger.info(f"No more users to fetch (total: {len(all_users)})")
            break
        
        for user in users:
            all_users[user.get("id")] = user
        
        logger.info(f"Fetched {len(users)} users (total: {len(all_users)})")
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
        time.sleep(0.5)
    
    return all_users


def fetch_incident_details(incident_id: str, token: str) -> Optional[Dict[str, Any]]:
    """Fetch detailed incident data including log entries."""
    params = {
        "include[]": ["services", "escalation_policies", "assignees", "first_trigger_log_entry"]
    }
    
    data = pagerduty_request(f"/incidents/{incident_id}", token, params)
    return data.get("incident") if data else None


def fetch_incident_logs(
    incident_id: str,
    token: str,
    log_types: List[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """Fetch log entries for an incident."""
    if not log_types:
        log_types = LOG_TYPES
    
    params = {
        "include[]": ["users", "services"],
        "types[]": log_types
    }
    
    all_logs = []
    offset = 0
    
    while True:
        params["offset"] = offset
        params["limit"] = BATCH_SIZE
        
        data = pagerduty_request(f"/incidents/{incident_id}/log_entries", token, params, limit=BATCH_SIZE)
        
        if data is None:
            logger.warning(f"Failed to fetch logs for incident {incident_id}")
            return None
        
        logs = data.get("log_entries", [])
        if not logs:
            break
        all_logs.extend(logs)
        
        if not data.get("more"):
            break
        
        offset += BATCH_SIZE
        time.sleep(0.2)
    
    return all_logs


def build_responder_records(
    incident: Dict[str, Any],
    log_entries: List[Dict[str, Any]],
    users_dict: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    responders: Dict[str, Dict[str, Any]] = {}

    assignments = incident.get("assignments", [])
    for assignment in assignments:
        assignee = assignment.get("assignee")
        if not isinstance(assignee, dict):
            continue
        responder_id = assignee.get("id") or assignee.get("email") or assignee.get("summary")
        if not responder_id:
            continue
        responder = {
            "responder_id": assignee.get("id"),
            "responder_name": assignee.get("summary") or assignee.get("name") or assignee.get("email"),
            "responder_email": assignee.get("email"),
            "responder_type": assignee.get("type"),
            "responder_teams_json": None
        }
        user = users_dict.get(assignee.get("id"))
        if user:
            responder["responder_email"] = responder["responder_email"] or user.get("email")
            teams = [t.get("summary") for t in user.get("teams", []) if isinstance(t, dict)]
            if teams:
                responder["responder_teams_json"] = json.dumps(teams, ensure_ascii=True)
        responders[responder_id] = responder

    for entry in log_entries:
        actor_summary = log_entry_actor_summary(entry)
        actor_id = None
        actor_email = None
        actor_type = None
        for key in ("agent", "user", "assignee", "responder"):
            actor = entry.get(key)
            if isinstance(actor, dict):
                actor_id = actor.get("id")
                actor_email = actor.get("email")
                actor_type = actor.get("type")
                break
        if not actor_summary:
            continue
        responder_key = actor_id or actor_email or actor_summary
        if responder_key not in responders:
            responders[responder_key] = {
                "responder_id": actor_id,
                "responder_name": actor_summary,
                "responder_email": actor_email,
                "responder_type": actor_type,
                "responder_teams_json": None
            }

    return list(responders.values())


def compute_responder_stats(incidents: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}

    for incident in incidents:
        responders = incident.get("responders", []) or []
        ack_by = incident.get("acknowledged_by")
        resolved_by = incident.get("resolved_by")
        tta = incident.get("tta_seconds")
        ttr = incident.get("ttr_seconds")
        response_effort = incident.get("response_effort_seconds")

        for responder in responders:
            name = responder.get("responder_name")
            if not name:
                continue
            entry = stats.setdefault(name, {
                "responder": name,
                "team": None,
                "incidents": 0,
                "acknowledged_incidents": 0,
                "acknowledged_incidents_pct": None,
                "interruptions": None,
                "notifications": None,
                "mtta_seconds": None,
                "mttr_seconds": None,
                "response_effort_seconds": None,
                "timeout_escalated_incidents": None,
                "manually_escalated_incidents": None,
                "_mtta_samples": [],
                "_mttr_samples": [],
                "_effort_samples": []
            })
            entry["incidents"] += 1

            teams_json = responder.get("responder_teams_json")
            if teams_json and not entry["team"]:
                try:
                    teams = json.loads(teams_json)
                    if teams:
                        entry["team"] = teams[0]
                except json.JSONDecodeError:
                    pass

            if ack_by and ack_by == name:
                entry["acknowledged_incidents"] += 1
                if tta is not None:
                    entry["_mtta_samples"].append(tta)

            if resolved_by and resolved_by == name and ttr is not None:
                entry["_mttr_samples"].append(ttr)

            if response_effort is not None:
                entry["_effort_samples"].append(response_effort)

    for responder, entry in stats.items():
        if entry["incidents"] > 0:
            entry["acknowledged_incidents_pct"] = (entry["acknowledged_incidents"] / entry["incidents"]) * 100
        if entry["_mtta_samples"]:
            entry["mtta_seconds"] = int(sum(entry["_mtta_samples"]) / len(entry["_mtta_samples"]))
        if entry["_mttr_samples"]:
            entry["mttr_seconds"] = int(sum(entry["_mttr_samples"]) / len(entry["_mttr_samples"]))
        if entry["_effort_samples"]:
            entry["response_effort_seconds"] = int(sum(entry["_effort_samples"]) / len(entry["_effort_samples"]))

        entry.pop("_mtta_samples", None)
        entry.pop("_mttr_samples", None)
        entry.pop("_effort_samples", None)

    return stats


def compute_service_stats(incidents: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}

    for incident in incidents:
        service_name = incident.get("service_name")
        if not service_name:
            continue
        entry = stats.setdefault(service_name, {
            "service": service_name,
            "team": None,
            "escalation_policy": incident.get("escalation_policy_name"),
            "uptime_pct": None,
            "incidents": 0,
            "acknowledged_incidents": 0,
            "acknowledged_incidents_pct": None,
            "auto_resolved_incidents": 0,
            "auto_resolved_incidents_pct": None,
            "mtta_seconds": None,
            "mttr_seconds": None,
            "response_effort_seconds": None,
            "total_escalations": 0,
            "_mtta_samples": [],
            "_mttr_samples": [],
            "_effort_samples": []
        })

        entry["incidents"] += 1
        if incident.get("acknowledgement_time"):
            entry["acknowledged_incidents"] += 1
        if incident.get("auto_resolved"):
            entry["auto_resolved_incidents"] += 1
        entry["total_escalations"] += int(incident.get("escalations_count") or 0)

        tta = incident.get("tta_seconds")
        ttr = incident.get("ttr_seconds")
        effort = incident.get("response_effort_seconds")
        if tta is not None:
            entry["_mtta_samples"].append(tta)
        if ttr is not None:
            entry["_mttr_samples"].append(ttr)
        if effort is not None:
            entry["_effort_samples"].append(effort)

    for service, entry in stats.items():
        if entry["incidents"] > 0:
            entry["acknowledged_incidents_pct"] = (entry["acknowledged_incidents"] / entry["incidents"]) * 100
            entry["auto_resolved_incidents_pct"] = (entry["auto_resolved_incidents"] / entry["incidents"]) * 100
        if entry["_mtta_samples"]:
            entry["mtta_seconds"] = int(sum(entry["_mtta_samples"]) / len(entry["_mtta_samples"]))
        if entry["_mttr_samples"]:
            entry["mttr_seconds"] = int(sum(entry["_mttr_samples"]) / len(entry["_mttr_samples"]))
        if entry["_effort_samples"]:
            entry["response_effort_seconds"] = int(sum(entry["_effort_samples"]) / len(entry["_effort_samples"]))

        entry.pop("_mtta_samples", None)
        entry.pop("_mttr_samples", None)
        entry.pop("_effort_samples", None)

    return stats


def fetch_logs_parallel(
    incidents: List[Dict[str, Any]],
    token: str
) -> Dict[str, List[Dict[str, Any]]]:
    logs_by_id: Dict[str, List[Dict[str, Any]]] = {}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for incident in incidents:
            incident_id = incident.get("id")
            if not incident_id:
                continue
            future = executor.submit(fetch_incident_logs, incident_id, token, LOG_TYPES)
            futures[future] = incident_id
        
        completed = 0
        for future in as_completed(futures):
            incident_id = futures[future]
            try:
                logs = future.result() or []
            except Exception as e:
                logger.warning(f"Log fetch failed for incident {incident_id}: {e}")
                logs = []
            logs_by_id[incident_id] = logs
            completed += 1
            if completed % 10 == 0:
                logger.info(f"Fetched logs for {completed}/{len(futures)} incidents")
    
    return logs_by_id


def enrich_incident(
    incident: Dict[str, Any],
    services_dict: Dict[str, Dict[str, Any]],
    users_dict: Dict[str, Dict[str, Any]],
    log_entries: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Enrich incident with service and user metadata."""
    log_entries = log_entries or []
    
    incident_id = incident.get("id")
    incident_number = incident.get("incident_number")
    custom_fields = extract_custom_fields(incident.get("custom_fields"))
    incident_type = incident.get("incident_type") or incident.get("type")
    status = incident.get("status")
    priority = None
    priority_obj = incident.get("priority")
    if isinstance(priority_obj, dict):
        priority = priority_obj.get("summary") or priority_obj.get("name")
    elif isinstance(priority_obj, str):
        priority = priority_obj

    trigger_time = first_log_entry_time(log_entries, ["incident.triggered"]) or parse_pd_timestamp(incident.get("created_at"))
    ack_time = first_log_entry_time(log_entries, ["incident.acknowledged"])
    resolved_entry = last_log_entry(log_entries, ["incident.resolved", "incident.auto_resolved"])
    resolved_time = parse_pd_timestamp(incident.get("resolved_at")) or parse_pd_timestamp(resolved_entry.get("created_at") if resolved_entry else None)
    resolved_by = log_entry_actor_summary(resolved_entry)
    # Check if incident was auto-resolved by checking the channel type
    auto_resolved = False
    if resolved_entry:
        channel = resolved_entry.get("channel", {})
        if isinstance(channel, dict):
            auto_resolved = channel.get("type") == "auto"
    escalations_count = len([entry for entry in log_entries if "escalate" in (entry.get("type") or "").lower()])


    responders = build_responder_records(incident, log_entries, users_dict)
    responders_display = ", ".join(sorted({r.get("responder_name") for r in responders if r.get("responder_name")})) or None

    acknowledgement_entry = last_log_entry(log_entries, ["incident.acknowledged"])
    acknowledged_by = log_entry_actor_summary(acknowledgement_entry)

    tta_seconds = None
    if ack_time and trigger_time:
        tta_seconds = int((ack_time - trigger_time).total_seconds())
        tta_seconds = max(0, tta_seconds)

    ttr_seconds = None
    if resolved_time and trigger_time:
        ttr_seconds = int((resolved_time - trigger_time).total_seconds())
        ttr_seconds = max(0, ttr_seconds)

    response_effort_seconds = None
    if ack_time and resolved_time:
        response_effort_seconds = int((resolved_time - ack_time).total_seconds())
        response_effort_seconds = max(0, response_effort_seconds)
    
    # Extract basic fields
    enriched = {
        "incident_id": incident_id,
        "incident_number": str(incident_number),
        "incident_type": str(incident_type) if incident_type and not isinstance(incident_type, dict) else None,
        "title": incident.get("title"),
        "description": incident.get("description"),
        "status": status,
        "urgency": incident.get("urgency"),
        "priority": priority,
        "service_id": None,
        "service_name": None,
        "escalation_policy_id": None,
        "escalation_policy_name": None,
        "created_at": parse_pd_timestamp(incident.get("created_at")),
        "created_at_hkt": to_hkt_datetime(incident.get("created_at")),
        "first_trigger_time": trigger_time,
        "acknowledgement_time": ack_time,
        "acknowledged_by": acknowledged_by,
        "resolved_at": resolved_time,
        "resolved_by": resolved_by,
        "auto_resolved": auto_resolved,
        "last_status_update_at": parse_pd_timestamp(incident.get("last_status_update_at")),
        "incident_key": incident.get("incident_key"),
        "responders_display": responders_display,
        "tta_seconds": tta_seconds,
        "ttr_seconds": ttr_seconds,
        "response_effort_seconds": response_effort_seconds,
        "escalations_count": escalations_count,
        "assignees_json": None,
        "responders": responders,
        "responder_metrics": None,
        "service_performance": None,
        "jj_test_custom_field": custom_fields.get("JJ Test Custom Field"),
        "jira_issue": custom_fields.get("Jira Issue"),
        "custom_fields_json": json.dumps(custom_fields, ensure_ascii=True) if custom_fields else None,
        "log_entries": [build_log_entry_record(entry) for entry in log_entries],
        "html_url": incident.get("html_url"),
        "sync_time": datetime.now(timezone.utc)
    }
    
    # Extract service info
    service = incident.get("service")
    if service:
        enriched["service_id"] = service.get("id")
        enriched["service_name"] = service.get("summary") or service.get("name")
        
        # Get escalation policy from service
        service_id = service.get("id")
        if service_id in services_dict:
            service_detail = services_dict[service_id]
            escalation_policy = service_detail.get("escalation_policy")
            if escalation_policy:
                enriched["escalation_policy_id"] = escalation_policy.get("id")
                enriched["escalation_policy_name"] = escalation_policy.get("summary") or escalation_policy.get("name")
    
    # Extract escalation policy direct
    escalation_policy = incident.get("escalation_policy")
    if escalation_policy:
        enriched["escalation_policy_id"] = escalation_policy.get("id")
        enriched["escalation_policy_name"] = escalation_policy.get("summary") or escalation_policy.get("name")
    
    # Extract assignees
    assignments = incident.get("assignments", [])
    assignees_json = extract_assignees(assignments)
    if assignees_json:
        enriched["assignees_json"] = assignees_json
    
    return enriched


def create_bigquery_schema() -> List[bigquery.SchemaField]:
    """Define BigQuery schema for consolidated PagerDuty incident data."""
    schema = [
        bigquery.SchemaField("incident_id", "STRING", mode="NULLABLE", description="PagerDuty incident ID"),
        bigquery.SchemaField("incident_number", "STRING", mode="REQUIRED", description="Unique incident number (merge key)"),
        bigquery.SchemaField("incident_type", "STRING", mode="NULLABLE", description="Incident type (CSV: Incident Type)"),
        bigquery.SchemaField("title", "STRING", mode="NULLABLE", description="Incident title"),
        bigquery.SchemaField("description", "STRING", mode="NULLABLE", description="Incident description"),
        bigquery.SchemaField("status", "STRING", mode="NULLABLE", description="Current incident status"),
        bigquery.SchemaField("urgency", "STRING", mode="NULLABLE", description="Incident urgency"),
        bigquery.SchemaField("priority", "STRING", mode="NULLABLE", description="Incident priority"),
        bigquery.SchemaField("service_id", "STRING", mode="NULLABLE", description="Associated service ID"),
        bigquery.SchemaField("service_name", "STRING", mode="NULLABLE", description="Associated service name"),
        bigquery.SchemaField("escalation_policy_id", "STRING", mode="NULLABLE", description="Escalation policy ID"),
        bigquery.SchemaField("escalation_policy_name", "STRING", mode="NULLABLE", description="Escalation policy name (clustering)"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="NULLABLE", description="Incident creation time (UTC)"),
        bigquery.SchemaField("created_at_hkt", "DATETIME", mode="NULLABLE", description="Incident creation time in HKT"),
        bigquery.SchemaField("first_trigger_time", "TIMESTAMP", mode="NULLABLE", description="First trigger log entry time"),
        bigquery.SchemaField("acknowledgement_time", "TIMESTAMP", mode="NULLABLE", description="Acknowledgement time"),
        bigquery.SchemaField("acknowledged_by", "STRING", mode="NULLABLE", description="Acknowledged by (CSV: Responders)"),
        bigquery.SchemaField("resolved_at", "TIMESTAMP", mode="NULLABLE", description="Resolution time (clustering)"),
        bigquery.SchemaField("resolved_by", "STRING", mode="NULLABLE", description="Resolved by (CSV: Resolved By)"),
        bigquery.SchemaField("auto_resolved", "BOOLEAN", mode="NULLABLE", description="Auto resolved flag"),
        bigquery.SchemaField("last_status_update_at", "TIMESTAMP", mode="NULLABLE", description="Last status update"),
        bigquery.SchemaField("incident_key", "STRING", mode="NULLABLE", description="Incident deduplication key"),
        bigquery.SchemaField("responders_display", "STRING", mode="NULLABLE", description="CSV-style responder list"),
        bigquery.SchemaField("tta_seconds", "INTEGER", mode="NULLABLE", description="TTA in seconds"),
        bigquery.SchemaField("ttr_seconds", "INTEGER", mode="NULLABLE", description="TTR in seconds"),
        bigquery.SchemaField("response_effort_seconds", "INTEGER", mode="NULLABLE", description="Response effort in seconds"),
        bigquery.SchemaField("escalations_count", "INTEGER", mode="NULLABLE", description="Escalations count"),
        bigquery.SchemaField("assignees_json", "STRING", mode="NULLABLE", description="JSON array of assigned user names"),
        bigquery.SchemaField(
            "responders",
            "RECORD",
            mode="REPEATED",
            fields=[
                bigquery.SchemaField("responder_id", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("responder_name", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("responder_email", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("responder_type", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("responder_teams_json", "STRING", mode="NULLABLE")
            ]
        ),
        bigquery.SchemaField(
            "responder_metrics",
            "RECORD",
            mode="REPEATED",
            fields=[
                bigquery.SchemaField("responder", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("team", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("acknowledged_incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("acknowledged_incidents_pct", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("interruptions", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("notifications", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("mtta_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("mttr_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("response_effort_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("timeout_escalated_incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("manually_escalated_incidents", "INTEGER", mode="NULLABLE")
            ]
        ),
        bigquery.SchemaField(
            "service_performance",
            "RECORD",
            mode="NULLABLE",
            fields=[
                bigquery.SchemaField("service", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("team", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("escalation_policy", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("uptime_pct", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("acknowledged_incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("acknowledged_incidents_pct", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("auto_resolved_incidents", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("auto_resolved_incidents_pct", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("mtta_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("mttr_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("response_effort_seconds", "INTEGER", mode="NULLABLE"),
                bigquery.SchemaField("total_escalations", "INTEGER", mode="NULLABLE")
            ]
        ),
        bigquery.SchemaField("jj_test_custom_field", "STRING", mode="NULLABLE", description="Custom field: JJ Test Custom Field"),
        bigquery.SchemaField("jira_issue", "STRING", mode="NULLABLE", description="Custom field: Jira Issue"),
        bigquery.SchemaField("custom_fields_json", "STRING", mode="NULLABLE", description="All custom fields as JSON"),
        bigquery.SchemaField(
            "log_entries",
            "RECORD",
            mode="REPEATED",
            fields=[
                bigquery.SchemaField("entry_type", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("created_at", "TIMESTAMP", mode="NULLABLE"),
                bigquery.SchemaField("actor_type", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("actor_id", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("actor_summary", "STRING", mode="NULLABLE")
            ]
        ),
        bigquery.SchemaField("html_url", "STRING", mode="NULLABLE", description="Link to incident in PagerDuty UI"),
        bigquery.SchemaField("sync_time", "TIMESTAMP", mode="REQUIRED", description="Data sync timestamp")
    ]
    return schema


def create_or_get_table(
    dataset_id: str,
    table_id: str,
    project_id: str,
    schema: List[bigquery.SchemaField]
) -> bigquery.Table:
    """Create table if it doesn't exist, return table reference."""
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    try:
        table = client.get_table(table_ref)
        logger.info(f"Table {table_ref} already exists")
        return table
    except NotFound:
        logger.info(f"Creating table {table_ref}")
        table = bigquery.Table(table_ref, schema=schema)
        
        # Configure clustering
        table.clustering_fields = ["escalation_policy_name", "resolved_at", "created_at"]
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="created_at"
        )
        
        table = client.create_table(table)
        logger.info(f"Created table {table_ref}")
        return table
    except Exception as e:
        logger.error(f"Error creating/getting table {table_ref}: {e}")
        raise


def delete_temp_table(client: bigquery.Client, dataset_id: str, table_id: str) -> None:
    """Delete temporary table."""
    try:
        client.delete_table(f"{client.project}.{dataset_id}.{table_id}")
        logger.info(f"Deleted temp table: {dataset_id}.{table_id}")
    except NotFound:
        pass
    except Exception as e:
        logger.warning(f"Error deleting temp table {dataset_id}.{table_id}: {e}")


def insert_to_bigquery(
    incidents: List[Dict[str, Any]],
    target_table: bigquery.Table
) -> Optional[int]:
    """Insert incidents to temp table and merge into target."""
    
    if not incidents:
        logger.info("No incidents to insert")
        return 0
    
    client = bigquery.Client(project=target_table.project)
    dataset_id = target_table.dataset_id
    table_id = target_table.table_id
    temp_table_id = f"{table_id}_temp_{int(datetime.now(timezone.utc).timestamp())}"
    
    try:
        # Step 1: Create and load to temp table
        logger.info(f"Creating temp table {dataset_id}.{temp_table_id}")
        temp_table_ref = f"{client.project}.{dataset_id}.{temp_table_id}"
        temp_table = bigquery.Table(temp_table_ref, schema=target_table.schema)
        temp_table = client.create_table(temp_table)
        
        logger.info(f"Inserting {len(incidents)} records into temp table")
        
        # Convert datetime objects to ISO format strings for JSON serialization
        incidents_serializable = [convert_datetimes_to_iso(incident) for incident in incidents]
        
        # Use insert_rows_json for better error handling
        errors = client.insert_rows_json(temp_table, incidents_serializable)
        if errors:
            logger.error(f"Errors inserting rows: {errors}")
            raise Exception(f"Failed to insert rows: {errors}")
        logger.info(f"Loaded {len(incidents)} records to temp table")
        
        all_fields = BQ_FIELDS
        update_pairs = [f"T.{field} = S.{field}" for field in all_fields if field != "incident_number"]
        update_set = ",\n                ".join(update_pairs)
        insert_columns = ", ".join(all_fields)
        insert_values = ", ".join([f"S.{field}" for field in all_fields])

        # Step 2: Merge temp into target
        merge_query = f"""
            MERGE `{target_table.project}.{target_table.dataset_id}.{target_table.table_id}` T
            USING (
                SELECT * EXCEPT(RowNum)
                FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY incident_number ORDER BY sync_time DESC) as RowNum
                    FROM `{client.project}.{dataset_id}.{temp_table_id}`
                )
                WHERE RowNum = 1
            ) S
            ON T.incident_number = S.incident_number
            WHEN MATCHED THEN UPDATE SET
                {update_set}
            WHEN NOT MATCHED THEN INSERT (
                {insert_columns}
            ) VALUES (
                {insert_values}
            )
        """
        
        logger.info("Executing MERGE query")
        job = client.query(merge_query)
        job.result()
        rows_merged = int(job.num_dml_affected_rows or 0)
        logger.info(f"MERGE completed: {rows_merged} rows affected")
        
        # Step 3: Clean up temp table
        delete_temp_table(client, dataset_id, temp_table_id)
        
        return rows_merged
        
    except Exception as e:
        logger.error(f"Error during insert/merge: {e}", exc_info=True)
        delete_temp_table(client, dataset_id, temp_table_id)
        return None


@functions_framework.http
def sync_pagerduty_incidents(request):
    """HTTP-triggered Cloud Function to sync PagerDuty incident data."""
    
    run_id = str(uuid.uuid4())
    pipeline_name = "PagerDutyIncidentData"
    
    try:
        project_id = "pccw-internal-virt-agent-uat"
        dataset_id = "GSO"
        table_id = "PagerDutyIncidentData"
        
        client = bigquery.Client(project=project_id)
        run_started = datetime.now(timezone.utc)
        
        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="PagerDuty Incident Data sync started",
            status="RUNNING",
            project=project_id,
            dataset=dataset_id
        )
        
        # Get API token
        token = get_secret("pagerduty-api-token", project_id=project_id)
        if not token:
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
            return {"error": "Failed to retrieve API token"}, 500
        
        # Parse parameters
        is_full_pull = request.args.get("full_pull", "false").lower() == "true"
        hours_back = int(request.args.get("hours_back", "3"))
        statuses_param = request.args.get("statuses", "")  # Empty = fetch all statuses
        statuses = [s.strip() for s in statuses_param.split(",") if s.strip()] if statuses_param else None
        
        logger.info(f"Starting sync - Full pull: {is_full_pull}, Hours back: {hours_back}, Statuses: {statuses or 'ALL'}")
        
        # Calculate since timestamp
        since = None
        if not is_full_pull:
            since = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
            logger.info(f"Delta sync since: {since}")
        
        # Create/get table
        schema = create_bigquery_schema()
        table = create_or_get_table(dataset_id, table_id, project_id, schema)
        logger.info(f"Using table: {table.project}.{table.dataset_id}.{table.table_id}")
        
        # Fetch reference data
        logger.info("Fetching services and users reference data")
        services_dict = fetch_services_dict(token)
        if services_dict is None:
            logger.warning("Failed to fetch services, continuing with partial data")
            services_dict = {}
        
        users_dict = fetch_users_dict(token)
        if users_dict is None:
            logger.warning("Failed to fetch users, continuing with partial data")
            users_dict = {}
        
        # Fetch incidents
        logger.info("Fetching incidents from PagerDuty API")
        incidents_list = fetch_incidents_paginated(token, since=since, statuses=statuses)
        
        if incidents_list is None:
            error_msg = "Failed to fetch incidents from PagerDuty API"
            logger.error(error_msg)
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message=error_msg,
                status="FAILED",
                error_code="API_FETCH_ERROR",
                project=project_id,
                dataset=dataset_id
            )
            return {"error": error_msg}, 500
        
        logger.info(f"Fetched {len(incidents_list)} incidents")

        logs_by_id = fetch_logs_parallel(incidents_list, token)
        
        # Enrich incidents
        enriched_incidents = []
        for incident in incidents_list:
            try:
                incident_id = incident.get("id")
                log_entries = logs_by_id.get(incident_id, [])
                enriched = enrich_incident(incident, services_dict, users_dict, log_entries)
                enriched_incidents.append(enriched)
            except Exception as e:
                incident_num = incident.get("incident_number", "unknown")
                logger.error(f"Error enriching incident {incident_num}: {e}")
                continue
        
        logger.info(f"Enriched {len(enriched_incidents)} incidents")

        responder_stats = compute_responder_stats(enriched_incidents)
        service_stats = compute_service_stats(enriched_incidents)

        for incident in enriched_incidents:
            responders = incident.get("responders", []) or []
            metrics = []
            for responder in responders:
                name = responder.get("responder_name")
                if name and name in responder_stats:
                    metrics.append(responder_stats[name])
            incident["responder_metrics"] = metrics or None
            service_name = incident.get("service_name")
            incident["service_performance"] = service_stats.get(service_name) if service_name else None
        
        # Insert to BigQuery
        rows_merged = 0
        if enriched_incidents:
            rows_merged = insert_to_bigquery(enriched_incidents, table)
            
            if rows_merged is None:
                log_pipeline_run(
                    client,
                    pipeline_name=pipeline_name,
                    run_id=run_id,
                    level="ERROR",
                    message="Failed to insert incidents into BigQuery",
                    status="FAILED",
                    error_code="INSERT_ERROR",
                    project=project_id,
                    dataset=dataset_id
                )
                return {"error": "Failed to insert incidents into BigQuery"}, 500
        
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
            rows_merged=rows_merged,
            duration_seconds=run_duration,
            project=project_id,
            dataset=dataset_id
        )
        
        return {
            "status": "success",
            "incidents_synced": len(enriched_incidents),
            "sync_type": "full" if is_full_pull else "delta",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": run_duration,
            "rows_merged": rows_merged
        }, 200
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        run_duration = (datetime.now(timezone.utc) - run_started).total_seconds() if 'run_started' in locals() else 0
        if 'client' in locals():
            log_pipeline_run(
                client,
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
        return {"error": str(e)}, 500
