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


def _get_latest_enabled_secret_version(client, secret_path: str):
    """Return the newest enabled secret version name, or None if none exist."""
    try:
        versions = list(client.list_secret_versions(request={"parent": secret_path}))
    except Exception as exc:  # pragma: no cover - defensive wrapper
        logging.warning(
            "Unable to list Secret Manager versions for %s: %s", secret_path, exc
        )
        return None

    enabled_versions = []
    for version in versions:
        version_name = getattr(version, "name", "")
        state = getattr(version, "state", None)
        state_name = (
            getattr(state, "name", str(state)).lower() if state is not None else ""
        )
        if state_name in {"enabled", "state.enabled"}:
            try:
                enabled_versions.append(
                    (int(version_name.rsplit("/", 1)[-1]), version_name)
                )
            except (TypeError, ValueError):
                continue

    if not enabled_versions:
        return None

    return max(enabled_versions, key=lambda item: item[0])[1]


def get_secret(
    secret_id: str, project_id: Optional[str] = None, version_id: str = "latest"
) -> Optional[str]:
    """
    Retrieve a secret from Google Cloud Secret Manager.

    If the alias resolves to a destroyed version, fall back to the newest enabled version.
    """
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logging.error(
                "GOOGLE_CLOUD_PROJECT env var not set and project_id not provided. "
                "Cannot retrieve secret from Secret Manager."
            )
            return None

    client = secretmanager.SecretManagerServiceClient()
    secret_path = f"projects/{project_id}/secrets/{secret_id}"

    try:
        name = f"{secret_path}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        logging.debug("Successfully retrieved secret: %s", secret_id)
        return secret_value
    except NotFound:
        logging.warning(
            "Secret '%s' latest alias not available for project %s; trying newest enabled version.",
            secret_id,
            project_id,
        )
    except PermissionDenied:
        logging.error(
            "Permission denied accessing secret '%s'. Ensure the service account has 'Secret Accessor' role.",
            secret_id,
        )
        return None
    except Exception as exc:
        logging.warning(
            "Secret '%s' lookup for version '%s' failed for project %s: %s; trying newest enabled version.",
            secret_id,
            version_id,
            project_id,
            exc,
        )

    fallback_version = _get_latest_enabled_secret_version(client, secret_path)
    if not fallback_version:
        logging.error(
            "Secret '%s' not found in Secret Manager for project %s",
            secret_id,
            project_id,
        )
        return None

    try:
        response = client.access_secret_version(request={"name": fallback_version})
        secret_value = response.payload.data.decode("UTF-8")
        logging.warning(
            "Recovered secret '%s' from fallback version %s after latest alias was unavailable.",
            secret_id,
            fallback_version,
        )
        return secret_value
    except NotFound:
        logging.error(
            "Secret '%s' not found in Secret Manager for project %s",
            secret_id,
            project_id,
        )
        return None
    except PermissionDenied:
        logging.error(
            "Permission denied accessing secret '%s'. Ensure the service account has 'Secret Accessor' role.",
            secret_id,
        )
        return None
    except Exception as exc:
        logging.error(
            "Error retrieving secret '%s' from Secret Manager: %s", secret_id, exc
        )
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
        project_id = os.environ.get(
            "GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat"
        )

    logging.info(
        f"Attempting to retrieve PagerDuty token from Secret Manager (project: {project_id})"
    )
    return get_secret("pagerduty-api-token", project_id)


def load_jira_credentials(
    project_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Load Jira API token and user email from Secret Manager.

    Returns:
        Tuple of (api_token, user_email) or (None, None) if not found
    """
    if not project_id:
        project_id = os.environ.get(
            "GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat"
        )

    token = get_secret("jira-api-token", project_id)
    email = get_secret("jira-user-email", project_id)

    if token and email:
        logging.info("Successfully loaded Jira credentials from Secret Manager")

    return token, email
