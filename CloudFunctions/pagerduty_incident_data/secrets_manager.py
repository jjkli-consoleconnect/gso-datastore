#!/usr/bin/env python3
"""
Secure credential management using Google Cloud Secret Manager.
All credentials should be stored in Secret Manager, not in code or config files.
"""

import logging
import os
from typing import Optional
from google.cloud import secretmanager
from google.api_core.exceptions import NotFound, PermissionDenied


def get_secret(
    secret_id: str,
    project_id: Optional[str] = None,
    version_id: str = "latest"
) -> Optional[str]:
    """
    Retrieve a secret from Google Cloud Secret Manager.
    
    Args:
        secret_id: The name of the secret (e.g., "pagerduty-api-token")
        project_id: GCP project ID. If not provided, uses GOOGLE_CLOUD_PROJECT env var
        version_id: Secret version to retrieve (default: "latest")
    
    Returns:
        The secret value as a string, or None if not found/accessible
    
    Raises:
        PermissionDenied: If the service account lacks access to the secret
        NotFound: If the secret doesn't exist
    """
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logging.error(
                "GOOGLE_CLOUD_PROJECT env var not set and project_id not provided. "
                "Cannot retrieve secret from Secret Manager."
            )
            return None
    
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        logging.debug(f"Successfully retrieved secret: {secret_id}")
        return secret_value
    except NotFound:
        logging.error(f"Secret '{secret_id}' not found in Secret Manager for project {project_id}")
        return None
    except PermissionDenied:
        logging.error(
            f"Permission denied accessing secret '{secret_id}'. "
            f"Ensure the service account has 'Secret Accessor' role."
        )
        return None
    except Exception as e:
        logging.error(f"Error retrieving secret '{secret_id}' from Secret Manager: {e}")
        return None


def load_pagerduty_token(project_id: Optional[str] = None) -> Optional[str]:
    """
    Load PagerDuty API token from Secret Manager.
    
    Priority order:
    1. PAGERDUTY_TOKEN environment variable (for local testing)
    2. Secret Manager (recommended for production)
    
    Args:
        project_id: GCP project ID for Secret Manager lookup
    
    Returns:
        PagerDuty API token or None if not found
    """
    # Check env var first (useful for local testing)
    token = os.environ.get("PAGERDUTY_TOKEN")
    if token:
        logging.info("Using PagerDuty token from PAGERDUTY_TOKEN env var")
        return token
    
    # Try Secret Manager
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat")
    
    logging.info(f"Attempting to retrieve PagerDuty token from Secret Manager (project: {project_id})")
    return get_secret("pagerduty-api-token", project_id)


def load_jira_credentials(project_id: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Load Jira API token and user email from Secret Manager.
    
    Returns:
        Tuple of (api_token, user_email) or (None, None) if not found
    """
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat")
    
    token = get_secret("jira-api-token", project_id)
    email = get_secret("jira-user-email", project_id)
    
    if token and email:
        logging.info("Successfully loaded Jira credentials from Secret Manager")
    
    return token, email
