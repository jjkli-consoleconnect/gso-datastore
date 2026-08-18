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
from urllib.parse import urlparse

import functions_framework
import requests
from google.cloud import secretmanager, bigquery
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
CLOSE_DUP_TABLE_ID = os.environ.get("JIRA_TO_HELIX_CLOSE_DUP_TABLE_ID", "jira_to_helix_close_dup_sync").strip()
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
JIRA_PROJECT = "MSS"

# Helix ticket defaults
HELIX_TICKET_TYPE = "Incident"
HELIX_PRIORITY = "Low"
HELIX_ASSIGNED_GROUP = "ASOC"
HELIX_CHANNEL = "API"
HELIX_WORKLOG_TYPE = "JIRA Work Log"
DEFAULT_MSS_CUSTOMER_ID = os.environ.get("JIRA_TO_HELIX_DEFAULT_CUSTOMER_ID", "TMSTKL").strip()
DEFAULT_ASOC_SR_NO = "SR128190"

# Jira custom fields for Helix ID backlink.
# Different Jira project/issue contexts expose different migrated field IDs.
JIRA_REMEDY_TICKET_NUMBER_FIELDS = [
    "customfield_10647",  # Legacy field ID
    "customfield_14905",  # Remedy Ticket Number (migrated)
    "customfield_10161",  # Remedy Ticket Number
    "customfield_15154",  # Remedy Incident Number
]
JIRA_MSS_CUSTOMER_FIELD = "customfield_11247"  # MSS customer / customer ID (preferred)
JIRA_CUSTOMER_ID_FIELD = "customfield_20270"  # Legacy customer ID field
JIRA_SR_NUMBER_FIELD = "customfield_10878"    # SR Number
JIRA_SR_REF_FIELD = "customfield_10228"       # SR Ref
JIRA_SP_SR_FIELD = "customfield_11510"        # SP # / SR #
JIRA_USN_FIELDS = [
    "customfield_10878",  # SR Number
    "customfield_10228",  # SR Ref
    "customfield_11510",  # SP # / SR #
    "customfield_11810",  # USN / Service Request identifier (common fallback)
    "customfield_11111",  # Generic fallback USN-like field
]

# Feature flags
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
DUPLICATE_ON_CLOSE_ENABLED = os.environ.get("DUPLICATE_ON_CLOSE_ENABLED", "true").lower() == "true"
ENABLE_HELIX_CLOSE_PATCH = os.environ.get("ENABLE_HELIX_CLOSE_PATCH", "true").lower() == "true"
ENABLE_HELIX_BACKDATE_FIELDS = os.environ.get("ENABLE_HELIX_BACKDATE_FIELDS", "false").lower() == "true"
ENFORCE_HELIX_ASSIGNED_GROUP = os.environ.get("ENFORCE_HELIX_ASSIGNED_GROUP", "true").lower() == "true"
CLOSE_DUP_CREATE_COOLDOWN_SECONDS = int(
    os.environ.get("JIRA_TO_HELIX_CLOSE_DUP_CREATE_COOLDOWN_SECONDS", "600")
)


CLOSE_DUP_PHASE_CREATE = "TICKET_CREATE"
CLOSE_DUP_PHASE_CLOSE = "TICKET_CLOSE"
CLOSE_DUP_PHASE_REPLAY_DONE = "WORKLOG_REPLAY_DONE"


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
        if resp.status_code >= 400:
            logger.error(
                "Helix create failed status=%s body=%s externalId=%s",
                resp.status_code,
                resp.text,
                payload.get("externalId", ""),
            )
        resp.raise_for_status()
        data = resp.json()
        helix_id = data.get("id")
        logger.info(f"Helix ticket created: {helix_id}")
        return helix_id
    except Exception as e:
        logger.error(f"Helix ticket creation failed: {e}")
        raise


def get_helix_ticket(ticket_id: str, token: str, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    """
    Retrieve a Helix trouble ticket by ID.

    Returns:
        Full ticket payload as a dict, or None on dry-run/error.
    """
    if not ticket_id:
        raise ValueError("ticket_id is required")

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
        url = f"https://{host_value}/cs-helix-ticketing/internalHelix/troubleTicket/{ticket_id}"
        if host_value and all(part.isdigit() for part in host_value.split(".") if part):
            verify_tls = False
    else:
        url = HELIX_API_BASE + f"troubleTicket/{ticket_id}"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-System-Id": "jira",
        "Content-Type": "application/json",
        "Host": HELIX_HOST_HEADER,
    }

    if dry_run:
        logger.info(f"[DRY-RUN] Would GET {url}")
        return None

    try:
        resp = requests.get(url, headers=headers, timeout=30, verify=verify_tls)
        if resp.status_code >= 400:
            logger.error(
                "Helix GET failed status=%s body=%s ticket_id=%s",
                resp.status_code,
                resp.text,
                ticket_id,
            )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Helix ticket fetched: {ticket_id}")
        return data
    except Exception as e:
        logger.error(f"Helix ticket fetch failed for {ticket_id}: {e}")
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


def patch_helix_ticket(
    helix_id: str,
    payload: Dict[str, Any],
    token: str,
    dry_run: bool = False,
) -> bool:
    """
    PATCH an existing Helix ticket with provided payload.
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

    if dry_run:
        logger.info(f"[DRY-RUN] Would PATCH {url} with payload: {json.dumps(payload, indent=2)}")
        return True

    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=30, verify=verify_tls)
        if resp.status_code >= 400:
            logger.error(
                f"Helix PATCH failed status={resp.status_code} body={resp.text}"
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Helix PATCH failed for {helix_id}: {e}")
        raise


def build_close_transition_payload(target_status: str) -> Dict[str, Any]:
    """
    Build a Helix PATCH payload for status transitions.

    The UAT tenant validates PATCH bodies more strictly than the create endpoint:
    a bare status patch can be rejected with 'Invalid empty notes', while a
    worklog-style note payload passes validation and still allows the status change.
    """
    return {
        "@type": "troubleTicket",
        "status": target_status,
        "notes": [
            {
                "id": "JIRA Work Log",
                "text": f"Jira-to-Helix auto-close transition to {target_status}",
                "@type": "worklog",
            }
        ],
    }


def close_helix_ticket(helix_id: str, token: str, dry_run: bool = False) -> str:
    """
    Move a Helix trouble ticket toward closure by PATCH status.

    Returns the final status that was successfully applied:
    - CLOSED
    - RESOLVED
    - IN PROGRESS

    Raises only when no fallback status can be applied.
    """
    close_attempts = [
        ["CLOSED"],
        ["IN PROGRESS", "RESOLVED", "CLOSED"],
    ]

    last_err: Optional[Exception] = None
    for path in close_attempts:
        try:
            for target_status in path:
                payload = build_close_transition_payload(target_status)
                patch_helix_ticket(helix_id, payload, token, dry_run=dry_run)
            logger.info(f"Helix close workflow applied on {helix_id} via path={path}")
            return path[-1]
        except Exception as e:
            last_err = e
            logger.warning(f"Helix close workflow path failed on {helix_id} path={path}: {e}")

    fallback_statuses = ["RESOLVED", "IN PROGRESS"]
    for fallback_status in fallback_statuses:
        try:
            payload = build_close_transition_payload(fallback_status)
            patch_helix_ticket(helix_id, payload, token, dry_run=dry_run)
            logger.warning(
                f"Helix terminal close not allowed for {helix_id}; fallback status applied={fallback_status}"
            )
            return fallback_status
        except Exception as e:
            last_err = e
            logger.warning(
                f"Helix fallback status failed on {helix_id} status={fallback_status}: {e}"
            )

    if last_err is not None:
        raise last_err
    raise RuntimeError(f"No status transition could be applied for {helix_id}")


def enforce_helix_assigned_group(
    helix_id: str,
    token: str,
    assigned_group: str,
    dry_run: bool = False,
) -> bool:
    """
    Best-effort overwrite of Helix assigned group after ticket creation.

    Helix appears to accept assignedGroup on create but may still route the
    ticket to another queue. This patch attempts to force the desired group
    from inside the same trusted network path used by the function.
    """
    payload = {
        "@type": "troubleTicket",
        "assignedGroup": assigned_group,
    }
    patch_helix_ticket(helix_id, payload, token, dry_run=dry_run)
    logger.info(f"Helix assignedGroup enforcement applied on {helix_id}: {assigned_group}")
    return True


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


def get_jira_comments(jira_key: str, jira_url: str, page_size: int = 100) -> list[Dict[str, Any]]:
    """
    Fetch all Jira comments with pagination.
    """
    email, token = get_jira_credentials()
    start_at = 0
    comments: list[Dict[str, Any]] = []

    while True:
        url = f"{jira_url}/rest/api/3/issue/{jira_key}/comment"
        params = {
            "startAt": start_at,
            "maxResults": page_size,
            "orderBy": "created",
        }
        resp = requests.get(url, params=params, auth=(email, token), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        page_values = data.get("comments", [])
        if isinstance(page_values, list):
            comments.extend(page_values)

        total = int(data.get("total", len(comments)))
        next_start = start_at + int(data.get("maxResults", page_size))
        if next_start >= total or not page_values:
            break
        start_at = next_start

    return comments


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
def extract_existing_jira_helix_id(fields: Dict[str, Any]) -> str:
    """
    Extract current Remedy/Helix ID from Jira issue fields.
    """
    if not isinstance(fields, dict):
        return ""

    for field_id in JIRA_REMEDY_TICKET_NUMBER_FIELDS:
        raw_value = fields.get(field_id)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return ""


def is_issue_created_event(webhook_event: Any, issue_event_type_name: str) -> bool:
    """
    Return True only for explicit issue-created webhook events.
    """
    webhook_event_text = str(webhook_event or "").strip().lower()
    issue_event_text = str(issue_event_type_name or "").strip().lower()
    return webhook_event_text == "jira:issue_created" or issue_event_text == "issue_created"


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

    block_types = {
        "doc",
        "blockquote",
        "bulletList",
        "orderedList",
        "listItem",
        "table",
        "tableRow",
    }

    def render(node: Any) -> str:
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return "".join(render(child) for child in node)
        if not isinstance(node, dict):
            return ""

        node_type = str(node.get("type", ""))
        if node_type == "text":
            return str(node.get("text", ""))
        if node_type == "hardBreak":
            return "\n"

        separator = "\n" if node_type in block_types else ""
        return separator.join(render(child) for child in node.get("content", []))

    return render(value).strip()


def extract_jira_attachment_labels(comment: Dict[str, Any]) -> list[str]:
    """
    Extract attachment/file names from Jira comment payload.

    Jira comment webhooks often encode uploaded images/files as ADF media nodes
    (attrs.alt) instead of comment.attachments.
    """
    labels: list[str] = []

    attachments = comment.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            content_url = str(item.get("content", "")).strip()
            if filename and content_url:
                labels.append(f"{filename}: {content_url}")
            elif filename:
                labels.append(filename)
            elif content_url:
                labels.append(content_url)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("type", "")).strip().lower()
            if node_type == "media":
                attrs = node.get("attrs", {})
                if isinstance(attrs, dict):
                    media_name = str(
                        attrs.get("alt")
                        or attrs.get("fileName")
                        or attrs.get("name")
                        or ""
                    ).strip()
                    if media_name:
                        labels.append(media_name)
                    else:
                        media_id = str(attrs.get("id", "")).strip()
                        if media_id:
                            labels.append(f"attachment-id:{media_id}")
            for child in node.get("content", []):
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(comment.get("body"))

    # Preserve order and de-duplicate.
    deduped: list[str] = []
    seen: set[str] = set()
    for item in labels:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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
            "comment_attachments": "",
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

    attachment_labels = extract_jira_attachment_labels(comment)

    return {
        "comment_id": str(comment.get("id", "")).strip(),
        "comment_body": flatten_jira_rich_text(comment.get("body")),
        "comment_created": comment_created,
        "comment_updated": comment_updated,
        "comment_event": "edited" if is_edited else "created",
        "comment_author": author_name,
        "comment_attachments": "\n".join(attachment_labels),
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

    attachment_block = (comment_data.get("comment_attachments", "") or "").strip()
    if attachment_block:
        note_text += f"\n\nAttachments (Jira):\n{attachment_block}"

    return {
        "id": HELIX_WORKLOG_TYPE,
        "text": note_text,
        "@type": "worklog",
    }


def build_helix_worklog_note_from_jira_comment(comment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build Helix worklog payload from Jira issue comment.
    """
    author_name = "jira"
    author = comment.get("author", {})
    if isinstance(author, dict):
        for key in ("displayName", "name", "emailAddress", "accountId"):
            raw = author.get(key)
            if isinstance(raw, str) and raw.strip():
                author_name = raw.strip()
                break

    created_ts = normalize_jira_timestamp(str(comment.get("created", "")))
    raw_updated = str(comment.get("updated", "")).strip()
    updated_ts = normalize_jira_timestamp(raw_updated) if raw_updated else created_ts

    body_text = flatten_jira_rich_text(comment.get("body"))
    if not body_text:
        body_text = "(Empty Jira comment)"

    attachment_lines = [f"- {label}" for label in extract_jira_attachment_labels(comment)]

    comment_id = str(comment.get("id", "")).strip() or "unknown"
    attachment_block = ""
    if attachment_lines:
        attachment_block = "\n\nAttachments (Jira):\n" + "\n".join(attachment_lines)

    note_text = (
        "Jira comment sync\n"
        f"Source comment ID: {comment_id}\n"
        f"Author: {author_name}\n"
        f"Created (Jira): {created_ts}\n"
        f"Updated (Jira): {updated_ts}\n\n"
        f"{body_text}"
        f"{attachment_block}"
    )

    return {
        "id": HELIX_WORKLOG_TYPE,
        "text": note_text,
        "@type": "worklog",
    }


def build_close_dup_comment_phase_key(comment: Dict[str, Any], close_cycle_key: str) -> str:
    """
    Build idempotency phase key for comment replay version.
    """
    comment_id = str(comment.get("id", "")).strip()
    if not comment_id:
        comment_id = "unknown"
    raw_updated = str(comment.get("updated", "")).strip()
    raw_created = str(comment.get("created", "")).strip()
    stamp = normalize_jira_timestamp(raw_updated or raw_created)
    return f"COMMENT_REPLAY:{close_cycle_key}:{comment_id}:{stamp}"


def build_close_cycle_key(fields: Dict[str, Any]) -> str:
    """
    Build a deterministic key for one Jira close cycle.
    """
    closed_raw = str(fields.get("resolutiondate", "")).strip()
    if closed_raw:
        closed_ts = normalize_jira_timestamp(closed_raw)
        close_marker = re.sub(r"[^0-9]", "", closed_ts)[:14]
        if close_marker:
            return f"CLOSE_{close_marker}"
    # Fallback protects malformed payloads while keeping key stable enough per invocation burst.
    return datetime.now(timezone.utc).strftime("CLOSE_%Y%m%d%H%M%S")


def extract_close_event_timestamp(fields: Dict[str, Any]) -> str:
    """
    Extract the best available close-event timestamp from Jira fields.
    """
    if not isinstance(fields, dict):
        return ""

    # resolutiondate is strongest close marker when present.
    resolution_raw = str(fields.get("resolutiondate", "")).strip()
    if resolution_raw:
        return normalize_jira_timestamp(resolution_raw)

    # Fallback for workflows that do not populate resolutiondate reliably.
    for key in ("statuscategorychangedate", "updated"):
        raw = str(fields.get(key, "")).strip()
        if raw:
            return normalize_jira_timestamp(raw)
    return ""


def issue_is_closed(fields: Dict[str, Any]) -> bool:
    """
    Determine whether Jira issue is in a closed/done state.
    """
    if not isinstance(fields, dict):
        return False

    status = fields.get("status", {})
    if isinstance(status, dict):
        status_name = str(status.get("name", "")).strip().lower()
        if status_name in {"closed", "done", "resolved"}:
            return True

        status_category = status.get("statusCategory", {})
        if isinstance(status_category, dict):
            category_key = str(status_category.get("key", "")).strip().lower()
            if category_key == "done":
                return True

    return False


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


def resolve_jira_issue_for_mapping(
    issue_data: Dict[str, Any],
    jira_key: str,
    jira_url: str,
) -> Dict[str, Any]:
    """Fetch the full Jira issue to avoid stale or synthetic webhook field values."""
    try:
        return get_jira_issue(jira_key, jira_url)
    except Exception as e:
        logger.warning(
            "Falling back to webhook issue payload for %s because Jira fetch failed: %s",
            jira_key,
            e,
        )
        if isinstance(issue_data, dict):
            return issue_data
        return {"fields": {}}


def _extract_first_text(value: Any, keys: Tuple[str, ...] = ()) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text

    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str):
                text = candidate.strip()
                if text:
                    return text

    return ""


def build_jira_source_description(
    fields: Dict[str, Any],
    jira_key: str,
    jira_customer_id: str,
    jira_sr_no: str,
) -> str:
    created_raw = str(fields.get("created", "")).strip()
    updated_raw = str(fields.get("updated", "")).strip()
    resolved_raw = str(fields.get("resolutiondate", "")).strip()

    assignee_name = _extract_first_text(
        fields.get("assignee", {}),
        ("displayName", "name", "emailAddress", "accountId"),
    )
    resolution_name = _extract_first_text(
        fields.get("resolution", {}),
        ("name", "value", "description"),
    )

    trace_lines = [
        "[Jira Source Trace]",
        f"Jira customer ID: {jira_customer_id or '(not provided)'}",
        f"Jira SR no: {jira_sr_no or '(not provided)'}",
    ]

    metadata_lines = [
        "[Jira Source Metadata]",
        f"Jira Key: {jira_key}",
        f"Jira Created: {normalize_jira_timestamp(created_raw) if created_raw else '(not provided)'}",
        f"Jira Updated: {normalize_jira_timestamp(updated_raw) if updated_raw else '(not provided)'}",
        f"Jira Resolved: {normalize_jira_timestamp(resolved_raw) if resolved_raw else '(not provided)'}",
        f"Jira Assignee: {assignee_name or '(unassigned)'}",
        f"Jira Resolution: {resolution_name or '(not provided)'}",
    ]

    return "\n".join(trace_lines + [""] + metadata_lines)


def map_jira_to_helix(
    jira_issue: Dict[str, Any],
    jira_key: str,
    jira_customer_id_override: str = "",
    jira_sr_no_override: str = "",
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
    
    jira_customer_id = jira_customer_id_override.strip()
    if not jira_customer_id:
        for field_id in (JIRA_MSS_CUSTOMER_FIELD, JIRA_CUSTOMER_ID_FIELD):
            raw_value = fields.get(field_id)
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if value:
                    jira_customer_id = value
                    break
            elif isinstance(raw_value, dict):
                for key in ("value", "name", "displayName"):
                    value = raw_value.get(key)
                    if isinstance(value, str) and value.strip():
                        jira_customer_id = value.strip()
                        break
                if jira_customer_id:
                    break

    jira_sr_no = jira_sr_no_override.strip()
    if not jira_sr_no:
        for field_id in (JIRA_SR_NUMBER_FIELD, JIRA_SR_REF_FIELD, JIRA_SP_SR_FIELD, *JIRA_USN_FIELDS):
            raw_value = fields.get(field_id)
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if value:
                    jira_sr_no = value
                    break
            elif isinstance(raw_value, dict):
                for key in ("value", "name", "displayName"):
                    value = raw_value.get(key)
                    if isinstance(value, str) and value.strip():
                        jira_sr_no = value.strip()
                        break
                if jira_sr_no:
                    break

    source_description = build_jira_source_description(fields, jira_key, jira_customer_id, jira_sr_no)
    if desc_text:
        desc_text = f"{desc_text}\n\n{source_description}"
    else:
        desc_text = source_description

    # Build Helix payload.
    # The UAT tenant accepts the create request only when the default customer/SR
    # pair is present as relatedEntity entries, so populate them explicitly.
    related_entity = [
        {
            "name": DEFAULT_MSS_CUSTOMER_ID,
            "role": "customerId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
        {
            "name": DEFAULT_ASOC_SR_NO,
            "role": "srId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
    ]

    resolved_status = ""
    status = fields.get("status", {})
    if isinstance(status, dict):
        status_name = str(status.get("name", "")).strip().upper()
        if status_name in {"RESOLVED", "CLOSED", "DONE"}:
            resolved_status = "RESOLVED"
        elif status_name == "IN PROGRESS":
            resolved_status = "IN PROGRESS"

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
                "text": "Others",
            },
            {
                "id": "item",
                "@type": "faultsymptom",
                "text": "Others",
            },
            {
                "id": "type",
                "@type": "faultsymptom",
                "text": "Others",
            }
        ],
    }

    if resolved_status:
        payload["status"] = resolved_status
    
    return payload


def map_jira_closed_issue_to_helix(
    jira_issue: Dict[str, Any],
    jira_key: str,
) -> Dict[str, Any]:
    """
    Build Helix payload for close-triggered duplication flow.
    """
    payload = map_jira_to_helix(jira_issue, jira_key)
    fields = jira_issue.get("fields", {})
    created_raw = str(fields.get("created", "")).strip()
    closed_raw = str(fields.get("resolutiondate", "")).strip()

    created_ts = normalize_jira_timestamp(created_raw) if created_raw else ""
    closed_ts = normalize_jira_timestamp(closed_raw) if closed_raw else ""

    # Re-close workflows can happen for the same Jira key; use a close-event
    # specific externalId to avoid Helix uniqueness collisions with prior creates.
    close_marker_source = closed_ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    close_marker = re.sub(r"[^0-9]", "", close_marker_source)[:14]
    payload["externalId"] = f"{jira_key}-C{close_marker}"

    details = [
        "",
        "",
        "[Jira Close Event]",
        f"Jira Key: {jira_key}",
    ]
    if closed_ts:
        details.append(f"Jira Closed: {closed_ts}")

    payload["description"] = (payload.get("description", "") + "\n".join(details)).strip()
    payload["status"] = "CLOSED"
    if ENABLE_HELIX_BACKDATE_FIELDS and created_ts:
        payload["creationDate"] = created_ts

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


def ensure_close_dup_sync_table() -> bool:
    """
    Ensure close-duplication idempotency table exists.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}"
        try:
            client.get_table(table_ref)
            return True
        except Exception:
            schema = [
                bigquery.SchemaField("jira_key", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("helix_id", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("phase_key", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("sync_status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("error_message", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("phase_meta", "STRING", mode="NULLABLE"),
                bigquery.SchemaField("created_timestamp", "TIMESTAMP", mode="REQUIRED"),
            ]
            table = bigquery.Table(table_ref, schema=schema)
            client.create_table(table)
            logger.info(f"Created BigQuery table {table_ref}")
            return True
    except Exception as e:
        logger.error(f"Failed ensuring close dup sync table: {e}")
        return False


def get_close_dup_phase_success(jira_key: str, phase_key: str) -> Optional[str]:
    """
    Return Helix ID for a successful phase if already recorded.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        query = f"""
        SELECT helix_id
        FROM `{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}`
        WHERE jira_key = @jira_key
          AND phase_key = @phase_key
          AND sync_status = 'success'
        ORDER BY created_timestamp DESC
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("jira_key", "STRING", jira_key),
                bigquery.ScalarQueryParameter("phase_key", "STRING", phase_key),
            ]
        )
        results = client.query(query, job_config=job_config).result()
        for row in results:
            helix_id = row.get("helix_id")
            if helix_id:
                return str(helix_id)
            return ""
    except Exception as e:
        logger.warning(f"Close dup phase check failed jira_key={jira_key} phase={phase_key}: {e}")
    return None


def get_latest_close_dup_create_success(jira_key: str) -> Optional[Dict[str, Any]]:
    """
    Fetch latest successful close-dup create record for a Jira key.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        query = f"""
        SELECT helix_id, phase_meta, created_timestamp
        FROM `{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}`
        WHERE jira_key = @jira_key
          AND phase_key LIKE @phase_like
          AND sync_status = 'success'
        ORDER BY created_timestamp DESC
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("jira_key", "STRING", jira_key),
                bigquery.ScalarQueryParameter("phase_like", "STRING", f"{CLOSE_DUP_PHASE_CREATE}:%"),
            ]
        )
        results = client.query(query, job_config=job_config).result()
        for row in results:
            meta_raw = row.get("phase_meta")
            phase_meta: Dict[str, Any] = {}
            if isinstance(meta_raw, str) and meta_raw.strip():
                try:
                    parsed = json.loads(meta_raw)
                    if isinstance(parsed, dict):
                        phase_meta = parsed
                except Exception:
                    phase_meta = {}
            return {
                "helix_id": str(row.get("helix_id") or "").strip(),
                "phase_meta": phase_meta,
                "created_timestamp": row.get("created_timestamp"),
            }
    except Exception as e:
        logger.warning(f"Latest close dup create lookup failed for {jira_key}: {e}")
    return None


def acquire_close_dup_window_lock(
    jira_key: str,
    lock_phase_key: str,
    phase_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Acquire a coarse cooldown-window lock in BigQuery to suppress burst duplicates.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        query = f"""
        INSERT INTO `{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}`
            (jira_key, helix_id, phase_key, sync_status, error_message, phase_meta, created_timestamp)
        SELECT
            @jira_key AS jira_key,
            CAST(NULL AS STRING) AS helix_id,
            @phase_key AS phase_key,
            'in_progress' AS sync_status,
            '' AS error_message,
            @phase_meta AS phase_meta,
            CURRENT_TIMESTAMP() AS created_timestamp
        FROM (SELECT 1) AS _dummy
        WHERE NOT EXISTS (
            SELECT 1
            FROM `{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}`
            WHERE jira_key = @jira_key
              AND phase_key = @phase_key
              AND sync_status IN ('in_progress', 'success')
        )
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("jira_key", "STRING", jira_key),
                bigquery.ScalarQueryParameter("phase_key", "STRING", lock_phase_key),
                bigquery.ScalarQueryParameter(
                    "phase_meta",
                    "STRING",
                    json.dumps(phase_meta or {}, ensure_ascii=True),
                ),
            ]
        )
        job = client.query(query, job_config=job_config)
        job.result()
        return int(getattr(job, "num_dml_affected_rows", 0) or 0) > 0
    except Exception as e:
        logger.warning(f"Close dup lock acquire failed jira_key={jira_key} phase={lock_phase_key}: {e}")
        return False


def record_close_dup_phase(
    jira_key: str,
    helix_id: Optional[str],
    phase_key: str,
    status: str,
    error_msg: str = "",
    phase_meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Record close-dup workflow phase result.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{CLOSE_DUP_TABLE_ID}"
        table = client.get_table(table_id)
        rows = [
            {
                "jira_key": jira_key,
                "helix_id": helix_id,
                "phase_key": phase_key,
                "sync_status": status,
                "error_message": error_msg,
                "phase_meta": json.dumps(phase_meta or {}, ensure_ascii=True),
                "created_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
        errors = client.insert_rows_json(table, rows)
        if errors:
            logger.error(f"BQ close dup insert errors: {errors}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to record close dup phase: {e}")
        return False


def process_closed_ticket_duplication(
    correlation_id: str,
    jira_key: str,
    issue_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """
    Duplicate a closed Jira ticket into Helix:
    create ticket, replay all comments as worklogs, then close Helix ticket.
    """
    if not ensure_close_dup_sync_table() and not DRY_RUN:
        return {"status": "error", "message": "Close-dup sync table unavailable"}, 500

    jira_issue = resolve_jira_issue_for_mapping(issue_data, jira_key, JIRA_SANDBOX_URL)

    jira_fields = jira_issue.get("fields", {})
    customer_id = DEFAULT_MSS_CUSTOMER_ID
    sr_no = DEFAULT_ASOC_SR_NO
    logger.warning(
        f"[{correlation_id}] Ignoring Jira customer field and forcing default customer/SR pair "
        f"customer={customer_id} sr={sr_no}"
    )

    close_cycle_key = build_close_cycle_key(jira_fields)
    incoming_close_ts = extract_close_event_timestamp(jira_fields)
    create_phase_key = f"{CLOSE_DUP_PHASE_CREATE}:{close_cycle_key}"
    replay_done_phase_key = f"{CLOSE_DUP_PHASE_REPLAY_DONE}:{close_cycle_key}"
    close_phase_key = f"{CLOSE_DUP_PHASE_CLOSE}:{close_cycle_key}"
    cooldown_window = max(int(CLOSE_DUP_CREATE_COOLDOWN_SECONDS), 1)
    cooldown_bucket = int(datetime.now(timezone.utc).timestamp()) // cooldown_window
    create_window_lock_phase_key = f"{CLOSE_DUP_PHASE_CREATE}:WINDOW:{cooldown_bucket}"

    created_phase_hit = get_close_dup_phase_success(jira_key, create_phase_key)
    helix_id = created_phase_hit if created_phase_hit is not None else ""

    # Drop stale retries and rapid duplicate close attempts for the same Jira key.
    latest_success = get_latest_close_dup_create_success(jira_key)
    if latest_success:
        latest_helix_id = str(latest_success.get("helix_id") or "").strip()
        latest_meta = latest_success.get("phase_meta") or {}
        latest_close_ts = str(latest_meta.get("close_ts") or "").strip()
        latest_created_ts = latest_success.get("created_timestamp")

        if incoming_close_ts and latest_close_ts and incoming_close_ts <= latest_close_ts:
            logger.warning(
                f"[{correlation_id}] Suppressing stale close event for {jira_key}: "
                f"incoming_close_ts={incoming_close_ts} <= latest_close_ts={latest_close_ts}"
            )
            return {
                "status": "duplicate_suppressed",
                "jira_key": jira_key,
                "helix_id": latest_helix_id,
                "message": "Stale close event suppressed",
                "correlation_id": correlation_id,
            }, 200

        if latest_created_ts is not None:
            try:
                age_seconds = (datetime.now(timezone.utc) - latest_created_ts).total_seconds()
            except Exception:
                age_seconds = None
            if age_seconds is not None and age_seconds < cooldown_window:
                logger.warning(
                    f"[{correlation_id}] Suppressing rapid duplicate close create for {jira_key}: "
                    f"age_seconds={age_seconds:.1f} cooldown={cooldown_window}"
                )
                return {
                    "status": "duplicate_suppressed",
                    "jira_key": jira_key,
                    "helix_id": latest_helix_id,
                    "message": "Close create cooldown active",
                    "correlation_id": correlation_id,
                }, 200

    helix_token = get_helix_token()
    if not helix_id:
        lock_meta = {
            "close_cycle_key": close_cycle_key,
            "close_ts": incoming_close_ts,
            "correlation_id": correlation_id,
        }
        lock_acquired = acquire_close_dup_window_lock(
            jira_key,
            create_window_lock_phase_key,
            phase_meta=lock_meta,
        )
        if not lock_acquired:
            logger.warning(
                f"[{correlation_id}] Suppressing duplicate close create in cooldown window for {jira_key} "
                f"phase={create_window_lock_phase_key}"
            )
            latest_hit = get_latest_close_dup_create_success(jira_key)
            latest_helix_id = ""
            if latest_hit:
                latest_helix_id = str(latest_hit.get("helix_id") or "").strip()
            return {
                "status": "duplicate_suppressed",
                "jira_key": jira_key,
                "helix_id": latest_helix_id,
                "message": "Close create already in progress or completed in cooldown window",
                "correlation_id": correlation_id,
            }, 200

        helix_payload = map_jira_closed_issue_to_helix(jira_issue, jira_key)
        logger.info(f"[{correlation_id}] Close-dup create payload: {json.dumps(helix_payload, indent=2)}")
        helix_id = create_helix_ticket(helix_payload, helix_token, dry_run=DRY_RUN) or ""
        if DRY_RUN and not helix_id:
            helix_id = f"DRYRUN-{jira_key}"
        if not helix_id:
            err = "Helix ticket creation returned no ID"
            if not DRY_RUN:
                record_close_dup_phase(jira_key, None, create_phase_key, "failed", err)
            return {"status": "error", "jira_key": jira_key, "message": err}, 500

        if not DRY_RUN:
            record_close_dup_phase(
                jira_key,
                helix_id,
                create_phase_key,
                "success",
                phase_meta={
                    "close_cycle_key": close_cycle_key,
                    "close_ts": incoming_close_ts,
                },
            )
            record_close_dup_phase(
                jira_key,
                helix_id,
                create_window_lock_phase_key,
                "success",
                phase_meta={
                    "close_cycle_key": close_cycle_key,
                    "close_ts": incoming_close_ts,
                },
            )
            update_jira_issue_field(
                jira_key,
                JIRA_REMEDY_TICKET_NUMBER_FIELDS,
                helix_id,
                JIRA_SANDBOX_URL,
            )
            if ENFORCE_HELIX_ASSIGNED_GROUP:
                try:
                    enforce_helix_assigned_group(
                        helix_id,
                        helix_token,
                        HELIX_ASSIGNED_GROUP,
                        dry_run=DRY_RUN,
                    )
                except Exception as e:
                    logger.warning(
                        f"[{correlation_id}] Helix assignedGroup enforcement failed for {helix_id}: {e}"
                    )

    replayed = 0
    skipped = 0
    failed = 0

    replay_done_hit = get_close_dup_phase_success(jira_key, replay_done_phase_key)
    if replay_done_hit is None:
        jira_comments = get_jira_comments(jira_key, JIRA_SANDBOX_URL)

        for comment in jira_comments:
            phase_key = build_close_dup_comment_phase_key(comment, close_cycle_key)
            if get_close_dup_phase_success(jira_key, phase_key) is not None:
                skipped += 1
                continue

            note = build_helix_worklog_note_from_jira_comment(comment)
            comment_id = str(comment.get("id", "")).strip()
            try:
                create_helix_worklog(helix_id, note, helix_token, dry_run=DRY_RUN)
                replayed += 1
                if not DRY_RUN:
                    record_close_dup_phase(
                        jira_key,
                        helix_id,
                        phase_key,
                        "success",
                        phase_meta={"comment_id": comment_id, "close_cycle_key": close_cycle_key},
                    )
            except Exception as e:
                failed += 1
                if not DRY_RUN:
                    record_close_dup_phase(
                        jira_key,
                        helix_id,
                        phase_key,
                        "failed",
                        str(e),
                        phase_meta={"comment_id": comment_id, "close_cycle_key": close_cycle_key},
                    )

        if failed == 0 and not DRY_RUN:
            record_close_dup_phase(
                jira_key,
                helix_id,
                replay_done_phase_key,
                "success",
                phase_meta={
                    "close_cycle_key": close_cycle_key,
                    "replayed": replayed,
                    "skipped": skipped,
                },
            )
    else:
        skipped += 1
        logger.info(f"[{correlation_id}] Replay already completed for cycle {close_cycle_key}; skip")

    if failed > 0:
        return {
            "status": "error",
            "jira_key": jira_key,
            "helix_id": helix_id,
            "message": "One or more comments failed during replay",
            "worklogs_replayed": replayed,
            "worklogs_skipped": skipped,
            "worklogs_failed": failed,
            "correlation_id": correlation_id,
        }, 500

    close_phase_hit = get_close_dup_phase_success(jira_key, close_phase_key)
    helix_final_status = "UNKNOWN"
    if close_phase_hit is None and ENABLE_HELIX_CLOSE_PATCH:
        try:
            helix_final_status = close_helix_ticket(helix_id, helix_token, dry_run=DRY_RUN)
            if not DRY_RUN:
                record_close_dup_phase(
                    jira_key,
                    helix_id,
                    close_phase_key,
                    "success",
                    phase_meta={
                        "close_cycle_key": close_cycle_key,
                        "final_status": helix_final_status,
                    },
                )
        except Exception as e:
            if not DRY_RUN:
                record_close_dup_phase(
                    jira_key,
                    helix_id,
                    close_phase_key,
                    "failed",
                    str(e),
                    phase_meta={"close_cycle_key": close_cycle_key},
                )
            return {
                "status": "error",
                "jira_key": jira_key,
                "helix_id": helix_id,
                "message": f"Failed to close Helix ticket: {e}",
                "worklogs_replayed": replayed,
                "worklogs_skipped": skipped,
                "correlation_id": correlation_id,
            }, 500
    elif close_phase_hit is not None:
        # A prior close phase exists for this cycle; keep response stable.
        helix_final_status = "CLOSED_OR_PREVIOUSLY_PROCESSED"

    send_slack_email_alert(jira_key, helix_id, "success")
    return {
        "status": "success" if not DRY_RUN else "dry_run",
        "jira_key": jira_key,
        "helix_id": helix_id,
        "worklogs_replayed": replayed,
        "worklogs_skipped": skipped,
        "closed_in_helix": ENABLE_HELIX_CLOSE_PATCH and helix_final_status == "CLOSED",
        "helix_final_status": helix_final_status,
        "correlation_id": correlation_id,
    }, 200


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
    force_reprocess = str(request.args.get("force", "")).strip().lower() in {"1", "true", "yes", "y"}
    if force_reprocess:
        logger.info(f"[{correlation_id}] Force reprocess enabled; bypassing idempotency cache")

    if request.method == "GET" and request.args.get("action") == "get_ticket":
        ticket_id = (request.args.get("ticket_id") or "").strip()
        if not ticket_id:
            return {"status": "error", "message": "Missing ticket_id"}, 400
        try:
            helix_token = get_helix_token()
            ticket = get_helix_ticket(ticket_id, helix_token, dry_run=False)
            return {
                "status": "success",
                "ticket_id": ticket_id,
                "ticket_status": ticket.get("status") if isinstance(ticket, dict) else None,
                "ticket": ticket,
            }, 200
        except Exception as e:
            return {"status": "error", "message": str(e)}, 500
    
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

        if DUPLICATE_ON_CLOSE_ENABLED:
            issue_fields = issue_data.get("fields") if isinstance(issue_data, dict) else {}
            if issue_is_closed(issue_fields):
                jira_key = str(issue_key_hint or issue_data.get("key") or "").strip()
                if not jira_key:
                    jira_key = extract_jira_key_fallback(webhook_data, raw_payload)
                if not jira_key:
                    logger.error(f"[{correlation_id}] No Jira key in close webhook")
                    return {"status": "error", "message": "Missing issue key"}, 400

                logger.info(f"[{correlation_id}] Processing closed-ticket duplication for {jira_key}")
                return process_closed_ticket_duplication(correlation_id, jira_key, issue_data)

        # Accept explicit issue-created events for legacy ticket creation flow.
        # Closed events are handled above when the issue payload indicates a resolved state.
        if not is_issue_created_event(webhook_event, issue_event_type_name):
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
        
        # Check idempotency unless explicitly bypassed for testing.
        cached_helix_id = ""
        if not force_reprocess:
            cached_helix_id = check_idempotency(jira_key)
        if cached_helix_id:
            # Avoid clobbering an existing Remedy ID on Jira with stale cached values.
            existing_issue_fields = issue_data.get("fields") if isinstance(issue_data, dict) else {}
            existing_helix_id = extract_existing_jira_helix_id(existing_issue_fields)
            if not existing_helix_id:
                update_jira_issue_field(
                    jira_key,
                    JIRA_REMEDY_TICKET_NUMBER_FIELDS,
                    cached_helix_id,
                    JIRA_SANDBOX_URL,
                )
            elif existing_helix_id != cached_helix_id:
                logger.warning(
                    f"[{correlation_id}] Cached Helix ID differs from Jira field for {jira_key}; "
                    f"keep existing Jira value existing={existing_helix_id} cached={cached_helix_id}"
                )
            logger.info(f"[{correlation_id}] {jira_key} already synced → {cached_helix_id}")
            return {"status": "cached", "jira_key": jira_key, "helix_id": cached_helix_id}, 200
        
        # Prefer issue fields from webhook payload when they contain the mapped fields.
        # Otherwise fetch the full Jira issue so customer/SR values are not lost.
        jira_issue = resolve_jira_issue_for_mapping(issue_data, jira_key, JIRA_SANDBOX_URL)

        customer_id = DEFAULT_MSS_CUSTOMER_ID
        sr_no = DEFAULT_ASOC_SR_NO
        logger.info(
            f"[{correlation_id}] Forcing default Helix customer/SR pair customer={customer_id} sr={sr_no}; Jira customer/SR fields are ignored"
        )
        
        # Map to Helix payload
        helix_payload = map_jira_to_helix(jira_issue, jira_key)
        logger.info(
            f"[{correlation_id}] Mapped payload customer={customer_id} sr={sr_no} "
            f"assignedGroup={helix_payload.get('assignedGroup')} relatedEntity={helix_payload.get('relatedEntity')}"
        )
        logger.info(f"[{correlation_id}] Helix payload to post: {json.dumps(helix_payload, indent=2)}")
        
        # Get Helix token
        helix_token = get_helix_token()
        
        # Create Helix ticket
        helix_id = create_helix_ticket(helix_payload, helix_token, dry_run=DRY_RUN)
        
        if helix_id and not DRY_RUN:
            try:
                helix_ticket = get_helix_ticket(helix_id, helix_token, dry_run=DRY_RUN)
                if helix_ticket:
                    related_entities = helix_ticket.get("relatedEntity") or []
                    related_map = {}
                    if isinstance(related_entities, list):
                        for item in related_entities:
                            if isinstance(item, dict):
                                role = str(item.get("role") or "").strip()
                                if role:
                                    related_map[role] = item.get("name")
                    logger.info(
                        f"[{correlation_id}] Helix ticket verification for {helix_id}: "
                        f"customerId={related_map.get('customerId')} srId={related_map.get('srId')} "
                        f"assignedGroup={helix_ticket.get('assignedGroup')}"
                    )
            except Exception as e:
                logger.warning(f"[{correlation_id}] Helix ticket verification failed for {helix_id}: {e}")

            try:
                jira_comments = get_jira_comments(jira_key, JIRA_SANDBOX_URL)
                if jira_comments:
                    logger.info(
                        f"[{correlation_id}] Replaying {len(jira_comments)} Jira comments to Helix ticket {helix_id}"
                    )
                    for comment in jira_comments:
                        comment_id = str(comment.get("id", "")).strip()
                        if not comment_id:
                            continue
                        note = build_helix_worklog_note_from_jira_comment(comment)
                        create_helix_worklog(helix_id, note, helix_token, dry_run=DRY_RUN)
                        logger.info(
                            f"[{correlation_id}] Replayed Jira comment {comment_id} to Helix ticket {helix_id}"
                        )
            except Exception as e:
                logger.warning(
                    f"[{correlation_id}] Failed to replay Jira comments to Helix ticket {helix_id}: {e}"
                )

            # Backlink Jira
            update_jira_issue_field(jira_key, JIRA_REMEDY_TICKET_NUMBER_FIELDS, helix_id, JIRA_SANDBOX_URL)
            if ENFORCE_HELIX_ASSIGNED_GROUP:
                try:
                    enforce_helix_assigned_group(
                        helix_id,
                        helix_token,
                        HELIX_ASSIGNED_GROUP,
                        dry_run=DRY_RUN,
                    )
                except Exception as e:
                    logger.warning(
                        f"[{correlation_id}] Helix assignedGroup enforcement failed for {helix_id}: {e}"
                    )
            
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


@functions_framework.http
def main(request):
    """HTTP entrypoint for Cloud Functions."""
    return jira_to_helix_create_uat(request)
