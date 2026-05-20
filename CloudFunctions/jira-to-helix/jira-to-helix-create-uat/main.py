"""
Cloud Function: Jira to Helix Create (UAT)
Receives Jira webhook when MSS ticket created, transforms to Helix incident payload,
creates Helix ticket with assigned_group=ASOC, backllinks to Jira with incident ID.
"""
import json
import logging
import uuid
import os
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

# Jira custom field for Helix ID backlink
JIRA_REMEDY_TICKET_NUMBER_FIELD = "customfield_10647"
JIRA_CUSTOMER_ID_FIELD = "customfield_11247"  # MSS customer

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


def update_jira_issue_field(jira_key: str, field_id: str, value: str, jira_url: str) -> bool:
    """
    Update Jira issue custom field.
    
    Args:
        jira_key: Issue key (e.g., MSS-123)
        field_id: Custom field ID (e.g., customfield_10647)
        value: New field value (e.g., Helix incident ID)
        jira_url: Base Jira URL
        
    Returns:
        True if successful
    """
    email, token = get_jira_credentials()
    url = f"{jira_url}/rest/api/3/issue/{jira_key}"
    
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
        logger.error(f"Jira update failed for {jira_key}: {e}")
        return False


# ===== FIELD MAPPING =====
def extract_jira_customer_id(fields: Dict[str, Any]) -> str:
    """
    Extract customer ID from Jira field customfield_11247 (MSS customer).

    Jira custom fields may be strings or objects depending on field configuration.
    """
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


def map_jira_to_helix(jira_issue: Dict[str, Any], jira_key: str, customer_id: str) -> Dict[str, Any]:
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
    payload = {
        "@type": "troubleTicket",
        "name": summary,
        "description": desc_text or "Created from Jira MSS ticket",
        "priority": HELIX_PRIORITY,
        "ticketType": HELIX_TICKET_TYPE,
        "externalId": jira_key,
        "relatedEntity": [
            {
                "name": customer_id,
                "role": "customerId",
                "@type": "RelatedEntity",
                "@referredType": "Profile"
            }
        ],
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
    HTTP Cloud Function: Jira webhook receiver for MSS issue creation.
    
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
    
    try:
        # Parse request
        webhook_data = request.get_json()
        if not webhook_data:
            return {"status": "error", "message": "Empty payload"}, 400
        
        webhook_event = webhook_data.get("webhookEvent")
        if webhook_event != "jira:issue_created":
            return {"status": "ignored", "message": f"Event {webhook_event} not handled"}, 200
        
        issue_data = webhook_data.get("issue", {})
        jira_key = issue_data.get("key")
        
        if not jira_key:
            logger.error(f"[{correlation_id}] No Jira key in webhook")
            return {"status": "error", "message": "Missing issue key"}, 400
        
        logger.info(f"[{correlation_id}] Processing {jira_key}")
        
        # Check idempotency
        cached_helix_id = check_idempotency(jira_key)
        if cached_helix_id:
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
        helix_payload = map_jira_to_helix(jira_issue, jira_key, customer_id)
        logger.info(f"[{correlation_id}] Mapped payload: {json.dumps(helix_payload, indent=2)}")
        
        # Get Helix token
        helix_token = get_helix_token()
        
        # Create Helix ticket
        helix_id = create_helix_ticket(helix_payload, helix_token, dry_run=DRY_RUN)
        
        if helix_id and not DRY_RUN:
            # Backlink Jira
            update_jira_issue_field(jira_key, JIRA_REMEDY_TICKET_NUMBER_FIELD, helix_id, JIRA_SANDBOX_URL)
            
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
