"""
Cloud Function: Jira to Helix Create (UAT)
Receives Jira webhook when MSS ticket created, transforms to Helix incident payload,
creates Helix ticket with assigned_group=ASOC, backllinks to Jira with incident ID.
"""
import json
import logging
import uuid
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
import hmac
import hashlib
from urllib.parse import urlparse

import functions_framework
import requests
from google.cloud import secretmanager, bigquery
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import urllib3

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== CONSTANTS =====
PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "Testing"
TABLE_ID = "jira_to_helix_sync"
COMMENT_TABLE_ID = "jira_to_helix_comment_sync"
SLACK_EMAIL = "jjkli-consoleconnect-aaaat6e6tqjcdqmox62y2vcqfi@consoleconnect.org.slack.com"

JIRA_TO_HELIX_JIRA_USER_EMAIL_SECRET = "jira-to-helix-jira-user-email"
JIRA_TO_HELIX_JIRA_API_TOKEN_SECRET = "jira-to-helix-jira-api-token"
JIRA_TO_HELIX_HELIX_CLIENT_ID_SECRET = "jira-to-helix-uat-helix-auth0-client-id"
JIRA_TO_HELIX_HELIX_CLIENT_SECRET = "jira-to-helix-uat-helix-auth0-client-secret"
JIRA_TO_HELIX_HOST_NAME_SECRET = "jira-to-helix-uat-host-name"

# Helix API Config
HELIX_AUTH_URL = "https://auth.stage.consoleconnect.com/oauth/token"
HELIX_API_BASE = "https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/"
HELIX_OAUTH_AUDIENCE = "api.stage.corp.consoleconnect.com"
HELIX_HOST_HEADER = "api.stage.corp.consoleconnect.com"

# Jira Config
JIRA_SANDBOX_URL = "https://consoleconnect-sandbox-824.atlassian.net"
JIRA_PROD_URL = "https://consoleconnect.atlassian.net"
JIRA_PROJECT = "MSS"

# Helix ticket defaults
HELIX_TICKET_TYPE = "Incident"
HELIX_PRIORITY = "Low"
HELIX_ASSIGNED_GROUP = "ASOC"
HELIX_CHANNEL = "API"
HELIX_WORKLOG_TYPE = "JIRA Work Log"
DEFAULT_MSS_CUSTOMER_ID = os.environ.get("JIRA_TO_HELIX_DEFAULT_CUSTOMER_ID", "TMS").strip()

# Jira custom fields for Helix ID backlink.
# Different Jira project/issue contexts expose different migrated field IDs.
JIRA_REMEDY_TICKET_NUMBER_FIELDS = [
    "customfield_10647",  # Legacy field ID
    "customfield_14905",  # Remedy Ticket Number (migrated)
    "customfield_10161",  # Remedy Ticket Number
    "customfield_15154",  # Remedy Incident Number
]
JIRA_ORGANIZATIONS_FIELD = "customfield_10002"  # Organizations
JIRA_CUSTOMER_ID_FIELD = "customfield_11247"  # MSS customer
JIRA_SR_NUMBER_FIELD = "customfield_10878"    # SR Number
JIRA_SR_REF_FIELD = "customfield_10228"       # SR Ref
JIRA_SP_SR_FIELD = "customfield_11510"        # SP # / SR #

# Feature flags
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


# ===== SECRET MANAGEMENT =====
def get_secret(secret_id: str) -> str:
    """
    Fetch secret from Google Secret Manager.
    
    Args:
        secret_id: Name of secret (without version)
        
    Returns:
        Secret value as string
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8").strip()
    except Exception as e:
        logger.error(f"Failed to fetch secret {secret_id}: {e}")
        raise


# ===== HELIX API =====
def get_helix_token() -> str:
    """
    Obtain OAuth2 token for Helix API.
    
    Returns:
        Bearer token string
    """
    client_id = get_secret(JIRA_TO_HELIX_HELIX_CLIENT_ID_SECRET)
    client_secret = get_secret(JIRA_TO_HELIX_HELIX_CLIENT_SECRET)
    
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": HELIX_OAUTH_AUDIENCE
    }
    
    try:
        # Helix auth endpoint expects form-encoded OAuth payload.
        resp = requests.post(HELIX_AUTH_URL, data=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")
    except Exception as e:
        logger.error(f"Helix auth failed: {e}")
        raise


def create_helix_ticket(payload: Dict[str, Any], token: str, dry_run: bool = False) -> Optional[str]:
    """
    Create Helix trouble ticket.
    
    Args:
        payload: Helix ticket payload (dict)
        token: OAuth2 bearer token
        dry_run: If True, log payload without posting
        
    Returns:
        Helix incident ID (e.g., INC000006741116) or None on error
    """
    host_name = get_secret(JIRA_TO_HELIX_HOST_NAME_SECRET)
    if host_name:
        host_name = host_name.strip()

    verify_tls = True
    if host_name:
        if host_name.startswith("http://") or host_name.startswith("https://"):
            parsed = urlparse(host_name)
            host_value = parsed.netloc or parsed.path
        else:
            host_value = host_name
        url = f"https://{host_value}/cs-helix-ticketing/internalHelix/troubleTicket"
        # jira-to-helix host secret stores a private IP; cert CN/SAN maps to public host header.
        if host_value and all(part.isdigit() for part in host_value.split(".") if part):
            verify_tls = False
    else:
        url = HELIX_API_BASE + "troubleTicket"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-System-Id": "jira",
        "Content-Type": "application/json",
        "Host": HELIX_HOST_HEADER,
    }
    
    if dry_run:
        logger.info(f"[DRY-RUN] Would POST to {url} with payload: {json.dumps(payload, indent=2)}")
        return None
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30, verify=verify_tls)
        resp.raise_for_status()
        data = resp.json()
        helix_id = data.get("id")
        logger.info(f"Helix ticket created: {helix_id}")
        return helix_id
    except Exception as e:
        logger.error(f"Helix ticket creation failed: {e}")
        raise


def create_helix_worklog(
    helix_id: str,
    note_payload: Dict[str, Any],
    token: str,
    dry_run: bool = False,
) -> bool:
    """
    Add a worklog note to an existing Helix trouble ticket via PATCH.

    Args:
        helix_id: Helix ticket ID (e.g., INC000006741116)
        note_payload: Single Helix note object with @type=worklog
        token: OAuth2 bearer token
        dry_run: If True, only log intended request

    Returns:
        True if PATCH succeeded
    """
    host_name = get_secret(JIRA_TO_HELIX_HOST_NAME_SECRET)
    if host_name:
        host_name = host_name.strip()

    verify_tls = True
    if host_name:
        if host_name.startswith("http://") or host_name.startswith("https://"):
            parsed = urlparse(host_name)
            host_value = parsed.netloc or parsed.path
        else:
            host_value = host_name
        url = f"https://{host_value}/cs-helix-ticketing/internalHelix/troubleTicket/{helix_id}"
        if host_value and all(part.isdigit() for part in host_value.split(".") if part):
            verify_tls = False
    else:
        url = HELIX_API_BASE + f"troubleTicket/{helix_id}"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-System-Id": "jira",
        "Content-Type": "application/json",
        "Host": HELIX_HOST_HEADER,
    }
    payload = {
        "@type": "troubleTicket",
        "notes": [note_payload],
    }

    if dry_run:
        logger.info(f"[DRY-RUN] Would PATCH {url} with payload: {json.dumps(payload, indent=2)}")
        return True

    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=30, verify=verify_tls)
        if resp.status_code >= 400:
            logger.error(
                f"Helix worklog PATCH failed status={resp.status_code} body={resp.text}"
            )
        resp.raise_for_status()
        logger.info(f"Helix worklog created on {helix_id}")
        return True
    except Exception as e:
        logger.error(f"Helix worklog creation failed for {helix_id}: {e}")
        raise


# ===== JIRA API =====
def get_jira_credentials() -> Tuple[str, str]:
    """
    Fetch Jira API credentials.
    
    Returns:
        (email, api_token)
    """
    email = get_secret(JIRA_TO_HELIX_JIRA_USER_EMAIL_SECRET)
    token = get_secret(JIRA_TO_HELIX_JIRA_API_TOKEN_SECRET)
    return email, token


def get_jira_issue(jira_key: str, jira_url: str) -> Dict[str, Any]:
    """
    Fetch Jira issue details via REST API.
    
    Args:
        jira_key: Issue key (e.g., MSS-123)
        jira_url: Base Jira URL (sandbox or prod)
        
    Returns:
        Issue data dict
    """
    email, token = get_jira_credentials()
    url = f"{jira_url}/rest/api/3/issue/{jira_key}"
    
    try:
        resp = requests.get(url, auth=(email, token), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Jira fetch failed for {jira_key}: {e}")
        raise


def update_jira_issue_field(jira_key: str, field_ids: list[str], value: str, jira_url: str) -> bool:
    """
    Update Jira issue custom field.
    
    Args:
        jira_key: Issue key (e.g., MSS-123)
        field_ids: Candidate custom field IDs
        value: New field value (e.g., Helix incident ID)
        jira_url: Base Jira URL
        
    Returns:
        True if successful
    """
    email, token = get_jira_credentials()
    url = f"{jira_url}/rest/api/3/issue/{jira_key}"
    
    for field_id in field_ids:
        payload = {
            "fields": {
                field_id: value
            }
        }
        try:
            resp = requests.put(url, json=payload, auth=(email, token), timeout=10)
            resp.raise_for_status()
            logger.info(f"Updated Jira {jira_key} field {field_id} = {value}")
            return True
        except Exception as e:
            logger.warning(f"Jira field update attempt failed for {jira_key} field {field_id}: {e}")

    logger.error(f"Jira update failed for {jira_key}: no candidate field accepted value")
    return False


# ===== FIELD MAPPING =====
def extract_jira_customer_id(fields: Dict[str, Any]) -> str:
    """
    Extract customer ID from Jira fields.

    Priority:
    1) Organizations (customfield_10002) organization name
    2) MSS customer (customfield_11247)

    Jira custom fields may be strings or objects depending on field configuration.
    """
    org_value = fields.get(JIRA_ORGANIZATIONS_FIELD)
    if isinstance(org_value, list):
        for org in org_value:
            if isinstance(org, dict):
                org_name = org.get("name")
                if isinstance(org_name, str) and org_name.strip():
                    return org_name.strip()
            elif isinstance(org, str) and org.strip():
                return org.strip()
            else:
                text_value = str(org).strip()
                if text_value:
                    return text_value
    elif isinstance(org_value, dict):
        org_name = org_value.get("name")
        if isinstance(org_name, str) and org_name.strip():
            return org_name.strip()

    raw_value = fields.get(JIRA_CUSTOMER_ID_FIELD)
    if raw_value is None:
        return ""
    if isinstance(raw_value, str):
        return raw_value.strip()
    if isinstance(raw_value, dict):
        for key in ("value", "name", "displayName"):
            value = raw_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(raw_value).strip()


def extract_jira_sr_no(fields: Dict[str, Any]) -> str:
    """
    Extract SR number with priority: SR Number, SR Ref, then SP # / SR #.
    """
    def normalize_sr(value: str) -> str:
        text = value.strip()
        if not text:
            return ""

        # Canonicalize common variants like "sr 12345" or "SR-12345".
        match = re.match(r"^sr[\s\-]*([0-9]+)$", text, flags=re.IGNORECASE)
        if match:
            return f"SR{match.group(1)}"

        # If Jira stores only digits, enforce the required SR prefix for Remedy.
        if re.match(r"^[0-9]+$", text):
            return f"SR{text}"

        return text

    for field_id in (JIRA_SR_NUMBER_FIELD, JIRA_SR_REF_FIELD, JIRA_SP_SR_FIELD):
        raw_value = fields.get(field_id)
        if raw_value is None:
            continue
        if isinstance(raw_value, str) and raw_value.strip():
            return normalize_sr(raw_value)
        if isinstance(raw_value, dict):
            for key in ("value", "name", "displayName"):
                value = raw_value.get(key)
                if isinstance(value, str) and value.strip():
                    return normalize_sr(value)
        text_value = str(raw_value).strip()
        if text_value:
            return normalize_sr(text_value)
    return ""


def flatten_jira_rich_text(value: Any) -> str:
    """
    Flatten Jira Atlassian Document Format or primitive text to plain text.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return str(value).strip()

    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text_value = node.get("text")
            if isinstance(text_value, str) and text_value:
                chunks.append(text_value)
            for child in node.get("content", []):
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return "\n".join(part.strip() for part in chunks if part and part.strip()).strip()


def normalize_jira_timestamp(value: str) -> str:
    """
    Normalize Jira datetime values into ISO-8601 UTC format accepted by Helix notes.date.
    """
    text = value.strip()
    if not text:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_jira_comment_data(webhook_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract comment details from Jira webhook payload for Helix worklog mapping.
    """
    comment = webhook_data.get("comment", {})
    if not isinstance(comment, dict):
        return {
            "comment_id": "",
            "comment_body": "",
            "comment_created": "",
            "comment_updated": "",
            "comment_event": "created",
            "comment_author": "jira",
        }

    author = comment.get("author", {})
    author_name = "jira"
    if isinstance(author, dict):
        for key in ("displayName", "name", "emailAddress", "accountId"):
            value = author.get(key)
            if isinstance(value, str) and value.strip():
                author_name = value.strip()
                break

    comment_created = normalize_jira_timestamp(str(comment.get("created", "")))
    raw_updated = str(comment.get("updated", "")).strip()
    comment_updated = normalize_jira_timestamp(raw_updated) if raw_updated else ""
    event_hint = str(webhook_data.get("webhookEvent", "")).lower()
    issue_event_hint = str(webhook_data.get("issue_event_type_name", "")).lower()
    is_edited = (
        (comment_updated and comment_updated != comment_created)
        or ("updated" in event_hint)
        or ("edited" in event_hint)
        or ("updated" in issue_event_hint)
        or ("edited" in issue_event_hint)
    )

    return {
        "comment_id": str(comment.get("id", "")).strip(),
        "comment_body": flatten_jira_rich_text(comment.get("body")),
        "comment_created": comment_created,
        "comment_updated": comment_updated,
        "comment_event": "edited" if is_edited else "created",
        "comment_author": author_name,
    }


def build_comment_sync_key(comment_data: Dict[str, str]) -> str:
    """
    Build idempotency key for comment create/edit versions.

    Uses comment ID plus effective event timestamp, allowing edits to sync
    while still deduplicating retries for the same comment version.
    """
    comment_id = comment_data.get("comment_id", "").strip()
    event_timestamp = (
        comment_data.get("comment_updated", "").strip()
        or comment_data.get("comment_created", "").strip()
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    return f"{comment_id}:{event_timestamp}"


def build_helix_worklog_note(comment_data: Dict[str, str]) -> Dict[str, Any]:
    """
    Build Helix worklog note from Jira comment fields.
    """
    comment_body = comment_data.get("comment_body", "").strip()
    event_type = comment_data.get("comment_event", "created")
    author = (comment_data.get("comment_author", "jira") or "jira").strip()
    message = comment_body or "(Empty Jira comment)"
    if event_type == "edited":
        note_text = f"{author} said (edited):\n\n{message}"
    else:
        note_text = f"{author} said:\n\n{message}"

    return {
        "id": HELIX_WORKLOG_TYPE,
        "text": note_text,
        "@type": "worklog",
    }


def parse_loose_jira_webhook_payload(raw_payload: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort parser for malformed Jira Automation payloads.

    Jira can emit invalid JSON when comment body contains literal newlines.
    This parser extracts required fields from raw text so processing can continue.
    """
    if not raw_payload or "\"comment\"" not in raw_payload or "\"issue\"" not in raw_payload:
        return None

    def extract(pattern: str) -> str:
        match = re.search(pattern, raw_payload, flags=re.IGNORECASE)
        if not match:
            return ""
        return (match.group(1) or "").strip()

    issue_key = extract(r'"key"\s*:\s*"([^"\\]+)"')
    comment_id = extract(r'"id"\s*:\s*"([^"\\]+)"')
    created = extract(r'"created"\s*:\s*"([^"\\]+)"')
    updated = extract(r'"updated"\s*:\s*"([^"\\]+)"')
    display_name = extract(r'"displayName"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
    account_id = extract(r'"accountId"\s*:\s*"([^"\\]+)"')
    webhook_event = extract(r'"webhookEvent"\s*:\s*"([^"\\]*)"')
    issue_event_type_name = extract(r'"issue_event_type_name"\s*:\s*"([^"\\]*)"')

    body_text = ""
    body_start = re.search(r'"body"\s*:\s*"', raw_payload, flags=re.IGNORECASE)
    if body_start:
        start = body_start.end()
        tail = raw_payload[start:]
        body_end = re.search(r'"\s*,\s*"author"\s*:', tail, flags=re.IGNORECASE | re.DOTALL)
        if body_end:
            body_text = tail[:body_end.start()]
        else:
            body_text = tail
        body_text = body_text.replace('\\"', '"').replace('\\n', '\n').replace('\\r', '\r').strip()

    if not issue_key or not comment_id:
        return None

    return {
        "webhookEvent": webhook_event,
        "issue_event_type_name": issue_event_type_name,
        "issue": {
            "key": issue_key,
        },
        "comment": {
            "id": comment_id,
            "created": created,
            "updated": updated,
            "body": body_text,
            "author": {
                "displayName": display_name,
                "accountId": account_id,
            },
        },
    }


def extract_jira_key_fallback(webhook_data: Dict[str, Any], raw_payload: str) -> str:
    """Extract Jira key from alternate webhook shapes or raw payload text."""
    issue = webhook_data.get("issue")
    if isinstance(issue, dict):
        issue_key = str(issue.get("key", "")).strip()
        if issue_key:
            return issue_key

    top_key = str(webhook_data.get("key", "")).strip()
    if top_key:
        return top_key

    issues = webhook_data.get("issues")
    if isinstance(issues, list):
        for item in issues:
            if not isinstance(item, dict):
                continue
            issue_key = str(item.get("key", "")).strip()
            if issue_key:
                return issue_key

    if isinstance(issue, str):
        issue_key = issue.strip()
        if issue_key:
            return issue_key

    project_prefix = re.escape(JIRA_PROJECT)
    match = re.search(rf'"key"\s*:\s*"({project_prefix}-\d+)"', raw_payload or "")
    if match:
        return match.group(1)

    # Last-resort fallback: capture an MSS-style issue key anywhere in payload text.
    broad_match = re.search(rf'\b{project_prefix}-\d+\b', raw_payload or "", flags=re.IGNORECASE)
    if broad_match:
        return broad_match.group(0).upper()

    return ""


def map_jira_to_helix(
    jira_issue: Dict[str, Any],
    jira_key: str,
    customer_id: str,
    sr_no: str = "",
) -> Dict[str, Any]:
    """
    Transform Jira MSS issue to Helix ticket payload.
    
    Args:
        jira_issue: Raw Jira issue data from API
        jira_key: Issue key for external reference
        
    Returns:
        Helix payload dict
    """
    fields = jira_issue.get("fields", {})
    
    # Extract Jira fields
    summary = fields.get("summary", "No title")
    description = fields.get("description", {})
    desc_text = ""
    if isinstance(description, dict):
        # Atlassian document format: flatten first-level text nodes safely.
        for block in description.get("content", []):
            for node in block.get("content", []):
                text_part = node.get("text")
                if text_part:
                    if desc_text:
                        desc_text += "\n"
                    desc_text += str(text_part)
    elif description is not None:
        desc_text = str(description)
    
    # Build Helix payload
    related_entity = [
        {
            "name": customer_id,
            "role": "customerId",
            "@type": "RelatedEntity",
            "@referredType": "Profile"
        }
    ]
    if sr_no:
        related_entity.append(
            {
                "name": sr_no,
                "role": "sr",
                "@type": "RelatedEntity",
                "@referredType": "Profile"
            }
        )

    payload = {
        "@type": "troubleTicket",
        "name": summary,
        "description": desc_text or "Created from Jira MSS ticket",
        "priority": HELIX_PRIORITY,
        "ticketType": HELIX_TICKET_TYPE,
        "externalId": jira_key,
        "relatedEntity": related_entity,
        "assignedGroup": HELIX_ASSIGNED_GROUP,
        "channel": {
            "name": HELIX_CHANNEL,
            "@type": "Customer"
        },
        "notes": [
            {
                "id": "category",
                "@type": "faultsymptom",
                "text": "Others"
            },
            {
                "id": "item",
                "@type": "faultsymptom",
                "text": "Others"
            },
            {
                "id": "type",
                "@type": "faultsymptom",
                "text": "Others"
            }
        ]
    }
    
    return payload


# ===== BIGQUERY IDEMPOTENCY =====
def check_idempotency(jira_key: str) -> Optional[str]:
    """
    Check if Jira key already synced to Helix (returns cached Helix ID).
    
    Args:
        jira_key: Jira issue key
        
    Returns:
        Helix ID if found, None otherwise
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        query = f"""
        SELECT helix_id FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE jira_key = @jira_key AND sync_status = 'success'
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("jira_key", "STRING", jira_key)]
        )
        results = client.query(query, job_config=job_config).result()
        for row in results:
            return row["helix_id"]
    except Exception as e:
        logger.warning(f"Idempotency check failed: {e}")
    
    return None


def record_sync(jira_key: str, helix_id: Optional[str], status: str, error_msg: str = "") -> bool:
    """
    Store sync result in BigQuery.
    
    Args:
        jira_key: Jira issue key
        helix_id: Helix incident ID (nullable)
        status: 'success' or 'failed'
        error_msg: Error message if failed
        
    Returns:
        True if successful
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
        table = client.get_table(table_id)
        
        rows = [
            {
                "jira_key": jira_key,
                "helix_id": helix_id,
                "created_timestamp": datetime.now(timezone.utc).isoformat(),
                "sync_status": status,
                "error_message": error_msg
            }
        ]
        
        errors = client.insert_rows_json(table, rows)
        if errors:
            logger.error(f"BQ insert errors: {errors}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to record sync: {e}")
        return False


def ensure_comment_sync_table() -> bool:
    """
    Ensure the comment idempotency table exists.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{COMMENT_TABLE_ID}"
        try:
            client.get_table(table_ref)
            return True
        except Exception:
            schema = [
                bigquery.SchemaField("jira_key", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("helix_id", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("comment_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("created_timestamp", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("sync_status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("error_message", "STRING", mode="NULLABLE"),
            ]
            table = bigquery.Table(table_ref, schema=schema)
            client.create_table(table)
            logger.info(f"Created BigQuery table {table_ref}")
            return True
    except Exception as e:
        logger.error(f"Failed ensuring comment sync table: {e}")
        return False


def check_comment_idempotency(comment_id: str) -> bool:
    """
    Check whether comment already synced to Helix worklog.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        query = f"""
        SELECT comment_id FROM `{PROJECT_ID}.{DATASET_ID}.{COMMENT_TABLE_ID}`
        WHERE comment_id = @comment_id AND sync_status = 'success'
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("comment_id", "STRING", comment_id)]
        )
        results = client.query(query, job_config=job_config).result()
        for _ in results:
            return True
    except Exception as e:
        logger.warning(f"Comment idempotency check failed: {e}")
    return False


def record_comment_sync(
    jira_key: str,
    helix_id: Optional[str],
    comment_id: str,
    status: str,
    error_msg: str = "",
) -> bool:
    """
    Store comment sync result in BigQuery.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{COMMENT_TABLE_ID}"
        table = client.get_table(table_id)
        rows = [
            {
                "jira_key": jira_key,
                "helix_id": helix_id,
                "comment_id": comment_id,
                "created_timestamp": datetime.now(timezone.utc).isoformat(),
                "sync_status": status,
                "error_message": error_msg,
            }
        ]
        errors = client.insert_rows_json(table, rows)
        if errors:
            logger.error(f"BQ comment insert errors: {errors}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to record comment sync: {e}")
        return False


# ===== EMAIL ALERT =====
def send_slack_email_alert(jira_key: str, helix_id: Optional[str], status: str, error_msg: str = "") -> bool:
    """
    Send email alert to Slack channel.
    
    Args:
        jira_key: Jira issue key
        helix_id: Helix incident ID (nullable)
        status: 'success' or 'failed'
        error_msg: Error message if failed
        
    Returns:
        True if successful
    """
    if DRY_RUN:
        logger.info(f"[DRY-RUN] Would send email alert for {jira_key} → {helix_id} ({status})")
        return True
    
    try:
        subject = f"Jira-to-Helix Sync: {jira_key} - {status.upper()}"
        
        if status == "success":
            body = f"""
            Jira-to-Helix sync completed successfully.
            
            Jira Key: {jira_key}
            Helix ID: {helix_id}
            Status: Success
            
            The Helix incident has been created and linked to the Jira ticket.
            """
        else:
            body = f"""
            Jira-to-Helix sync failed.
            
            Jira Key: {jira_key}
            Status: Failed
            Error: {error_msg}
            
            Please investigate.
            """
        
        # For now, just log the message
        # TODO: Integrate with SendGrid or SMTP
        logger.info(f"Email Alert:\nTo: {SLACK_EMAIL}\nSubject: {subject}\nBody: {body}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False


# ===== WEBHOOK HANDLER =====
@functions_framework.http
def jira_to_helix_create_uat(request):
    """
    HTTP Cloud Function: Jira webhook receiver for MSS issue creation and comments.
    
    Expected webhook payload (Jira):
    {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "MSS-123",
            "fields": {
                "summary": "...",
                "description": {...}
            }
        }
    }
    """
    correlation_id = str(uuid.uuid4())
    logger.info(f"[{correlation_id}] Webhook received")
    
    jira_key = ""

    try:
        raw_payload = request.get_data(as_text=True) or ""

        # Parse request. Use silent mode so malformed JSON returns a controlled 400 instead of raising.
        webhook_data = request.get_json(silent=True)
        if webhook_data is None:
            recovered_payload = parse_loose_jira_webhook_payload(raw_payload)
            if recovered_payload is not None:
                webhook_data = recovered_payload
                logger.warning(
                    f"[{correlation_id}] Recovered malformed Jira JSON payload via loose parser"
                )
            else:
                logger.error(
                    f"[{correlation_id}] Invalid JSON payload received. "
                    f"First 500 chars: {raw_payload[:500]}"
                )
                return {
                    "status": "error",
                    "message": "Invalid JSON payload",
                }, 400
        
        webhook_event = webhook_data.get("webhookEvent")
        issue_event_type_name = str(webhook_data.get("issue_event_type_name", "")).lower()

        # Jira Automation can send issue payloads without webhookEvent.
        issue_data = webhook_data.get("issue", {})
        issue_key_hint = issue_data.get("key") if isinstance(issue_data, dict) else None
        if not issue_key_hint:
            issue_key_hint = extract_jira_key_fallback(webhook_data, raw_payload)

        # Some Jira automation payload shapes omit issue.key but include issue.id (or top-level id).
        if not issue_key_hint:
            issue_identifier = ""
            if isinstance(issue_data, dict):
                issue_identifier = str(issue_data.get("id", "")).strip()
            if not issue_identifier:
                issue_identifier = str(webhook_data.get("id", "")).strip()

            if issue_identifier:
                try:
                    resolved_issue = get_jira_issue(issue_identifier, JIRA_SANDBOX_URL)
                    resolved_key = str(resolved_issue.get("key", "")).strip()
                    if resolved_key:
                        issue_key_hint = resolved_key
                        if isinstance(issue_data, dict):
                            issue_data = resolved_issue
                        logger.info(
                            f"[{correlation_id}] Resolved Jira key from issue id {issue_identifier}: {resolved_key}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[{correlation_id}] Could not resolve Jira key from issue id {issue_identifier}: {e}"
                    )

        if not isinstance(issue_data, dict):
            issue_data = {}

        if issue_key_hint and not issue_data.get("key"):
            issue_data["key"] = issue_key_hint

        if issue_data:
            webhook_data["issue"] = issue_data
        has_comment = isinstance(webhook_data.get("comment"), dict)

        if has_comment:
            jira_key = str(issue_key_hint or "").strip()
            if not jira_key:
                logger.error(f"[{correlation_id}] No Jira key in comment webhook")
                return {"status": "error", "message": "Missing issue key"}, 400

            logger.info(f"[{correlation_id}] Processing Jira comment webhook for {jira_key}")
            if not ensure_comment_sync_table():
                return {"status": "error", "message": "Comment sync table unavailable"}, 500

            comment_data = extract_jira_comment_data(webhook_data)
            source_comment_id = comment_data.get("comment_id", "")
            if not source_comment_id:
                logger.error(f"[{correlation_id}] Missing comment ID in webhook")
                return {"status": "error", "message": "Missing comment ID"}, 400

            comment_sync_key = build_comment_sync_key(comment_data)

            if check_comment_idempotency(comment_sync_key):
                logger.info(f"[{correlation_id}] Comment version already synced: {comment_sync_key}")
                return {
                    "status": "cached",
                    "jira_key": jira_key,
                    "comment_id": source_comment_id,
                    "comment_sync_key": comment_sync_key,
                    "message": "Comment version already synced",
                }, 200

            issue_fields = issue_data.get("fields") if isinstance(issue_data, dict) else None
            if not isinstance(issue_fields, dict) or not issue_fields:
                jira_issue = get_jira_issue(jira_key, JIRA_SANDBOX_URL)
                issue_fields = jira_issue.get("fields", {})

            helix_id = ""
            for field_id in JIRA_REMEDY_TICKET_NUMBER_FIELDS:
                raw_value = issue_fields.get(field_id)
                if raw_value is None:
                    continue
                value = str(raw_value).strip()
                if value:
                    helix_id = value
                    break

            if not helix_id:
                error_msg = "No Remedy ticket number found on Jira issue"
                record_comment_sync(jira_key, None, comment_sync_key, "failed", error_msg)
                logger.error(f"[{correlation_id}] {error_msg} for {jira_key}")
                return {
                    "status": "error",
                    "jira_key": jira_key,
                    "comment_id": source_comment_id,
                    "comment_sync_key": comment_sync_key,
                    "message": error_msg,
                }, 400

            worklog_note = build_helix_worklog_note(comment_data)
            helix_token = get_helix_token()
            create_helix_worklog(helix_id, worklog_note, helix_token, dry_run=DRY_RUN)

            record_comment_sync(jira_key, helix_id, comment_sync_key, "success")
            logger.info(
                f"[{correlation_id}] ✓ Comment sync complete: {jira_key} comment={source_comment_id} "
                f"event={comment_data.get('comment_event')} key={comment_sync_key} → {helix_id}"
            )
            return {
                "status": "success" if not DRY_RUN else "dry_run",
                "jira_key": jira_key,
                "helix_id": helix_id,
                "comment_id": source_comment_id,
                "comment_sync_key": comment_sync_key,
                "comment_event": comment_data.get("comment_event", "created"),
                "correlation_id": correlation_id,
            }, 200

        # Accept issue-created events for ticket creation flow.
        is_issue_created_event = (
            webhook_event == "jira:issue_created"
            or issue_event_type_name == "issue_created"
            or (webhook_event is None and bool(issue_key_hint))
        )
        if not is_issue_created_event:
            logger.info(
                f"[{correlation_id}] Ignored webhook event. "
                f"webhookEvent={webhook_event}, issue_event_type_name={issue_event_type_name}, issue_key={issue_key_hint}"
            )
            return {
                "status": "ignored",
                "message": f"Event {webhook_event or issue_event_type_name or 'unknown'} not handled"
            }, 200
        
        issue_data = webhook_data.get("issue", {}) if isinstance(webhook_data.get("issue"), dict) else {}
        jira_key = str(issue_data.get("key") or issue_key_hint or "").strip()

        if not jira_key:
            jira_key = extract_jira_key_fallback(webhook_data, raw_payload)
        
        if not jira_key:
            logger.error(
                f"[{correlation_id}] No Jira key in webhook. "
                f"Top-level keys: {list(webhook_data.keys())[:20]}"
            )
            return {"status": "error", "message": "Missing issue key"}, 400
        
        logger.info(f"[{correlation_id}] Processing {jira_key}")
        
        # Check idempotency
        cached_helix_id = check_idempotency(jira_key)
        if cached_helix_id:
            # Ensure backlink exists even when replaying an already-synced ticket.
            update_jira_issue_field(
                jira_key,
                JIRA_REMEDY_TICKET_NUMBER_FIELDS,
                cached_helix_id,
                JIRA_SANDBOX_URL,
            )
            logger.info(f"[{correlation_id}] {jira_key} already synced → {cached_helix_id}")
            return {"status": "cached", "jira_key": jira_key, "helix_id": cached_helix_id}, 200
        
        # Prefer issue fields from webhook payload to avoid extra Jira read call.
        # Fallback to Jira API fetch only if fields are missing.
        issue_fields = issue_data.get("fields")
        if isinstance(issue_fields, dict) and issue_fields:
            jira_issue = issue_data
        else:
            jira_issue = get_jira_issue(jira_key, JIRA_SANDBOX_URL)

        jira_fields = jira_issue.get("fields", {})
        customer_id = extract_jira_customer_id(jira_fields)
        sr_no = extract_jira_sr_no(jira_fields)
        if not customer_id and DEFAULT_MSS_CUSTOMER_ID:
            customer_id = DEFAULT_MSS_CUSTOMER_ID
            logger.warning(
                f"[{correlation_id}] Missing {JIRA_CUSTOMER_ID_FIELD}; "
                f"falling back to default customer ID {DEFAULT_MSS_CUSTOMER_ID}"
            )
        if sr_no:
            logger.info(
                f"[{correlation_id}] SR value mapped from Jira fields "
                f"{JIRA_SR_NUMBER_FIELD}/{JIRA_SR_REF_FIELD}/{JIRA_SP_SR_FIELD}: {sr_no}"
            )
        if not customer_id:
            error_msg = (
                f"Missing Jira MSS customer ID field {JIRA_CUSTOMER_ID_FIELD}"
            )
            record_sync(jira_key, None, "failed", error_msg)
            send_slack_email_alert(jira_key, None, "failed", error_msg)
            logger.error(f"[{correlation_id}] {error_msg}")
            return {
                "status": "error",
                "jira_key": jira_key,
                "message": error_msg,
            }, 400
        
        # Map to Helix payload
        helix_payload = map_jira_to_helix(jira_issue, jira_key, customer_id, sr_no)
        logger.info(f"[{correlation_id}] Mapped payload: {json.dumps(helix_payload, indent=2)}")
        
        # Get Helix token
        helix_token = get_helix_token()
        
        # Create Helix ticket
        helix_id = create_helix_ticket(helix_payload, helix_token, dry_run=DRY_RUN)
        
        if helix_id and not DRY_RUN:
            # Backlink Jira
            update_jira_issue_field(jira_key, JIRA_REMEDY_TICKET_NUMBER_FIELDS, helix_id, JIRA_SANDBOX_URL)
            
            # Record success
            record_sync(jira_key, helix_id, "success")
            
            # Alert
            send_slack_email_alert(jira_key, helix_id, "success")
            
            logger.info(f"[{correlation_id}] ✓ Sync complete: {jira_key} → {helix_id}")
            return {
                "status": "success",
                "jira_key": jira_key,
                "helix_id": helix_id,
                "correlation_id": correlation_id
            }, 200
        elif DRY_RUN:
            logger.info(f"[{correlation_id}] [DRY-RUN] Would complete: {jira_key}")
            return {
                "status": "dry_run",
                "jira_key": jira_key,
                "payload": helix_payload,
                "correlation_id": correlation_id
            }, 200
        else:
            # Record failure
            error_msg = "Helix ticket creation returned no ID"
            record_sync(jira_key, None, "failed", error_msg)
            send_slack_email_alert(jira_key, None, "failed", error_msg)
            
            logger.error(f"[{correlation_id}] ✗ Failed: {jira_key}")
            return {"status": "error", "message": error_msg}, 500
    
    except Exception as e:
        logger.error(f"[{correlation_id}] Exception: {e}", exc_info=True)
        
        # Best-effort failure recording
        try:
            if jira_key:
                record_sync(jira_key, None, "failed", str(e))
                send_slack_email_alert(jira_key, None, "failed", str(e))
        except:
            pass
        
        return {"status": "error", "message": str(e)}, 500
