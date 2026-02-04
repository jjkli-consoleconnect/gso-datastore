#!/usr/bin/env python3
"""
Secure credential management using Google Cloud Secret Manager.
All credentials should be stored in Secret Manager, not in code or config files.
"""

import logging
from typing import Optional
from google.cloud import secretmanager
from google.api_core.exceptions import NotFound, PermissionDenied


def get_secret(
    secret_id: str,
    project_id: str = "pccw-internal-virt-agent-uat",
    version_id: str = "latest"
) -> Optional[str]:
    """
    Retrieve a secret from Google Cloud Secret Manager.
    
    Args:
        secret_id: The name of the secret (e.g., "pagerduty-api-token")
        project_id: GCP project ID (default: pccw-internal-virt-agent-uat)
        version_id: Secret version to retrieve (default: "latest")
    
    Returns:
        The secret value as a string, or None if not found/accessible
    """
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
