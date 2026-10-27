"""Function setup command: browser consent -> verification -> Secret Manager."""

import argparse
import json
import logging

from google.cloud import secretmanager
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from calendar_auth import (
    EXPECTED_USER_EMAIL,
    OAUTH_SCOPES,
    CalendarAuthError,
    require_calendar_write_access,
    verified_user_credentials,
)
from main import CALENDAR_ID, OAUTH_SECRET, PROJECT_ID


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-secrets", required=True, help="Approved Desktop OAuth client JSON.")
    args = parser.parse_args()
    with open(args.client_secrets, encoding="utf-8") as handle:
        client_info = json.load(handle)
    if not isinstance(client_info, dict) or not isinstance(client_info.get("installed"), dict):
        raise CalendarAuthError("Use a Desktop OAuth client JSON, not a service-account key or user token.")

    # The library's INFO callback logs include the authorization code in the URL.
    logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.WARNING)
    logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("oauthlib").setLevel(logging.WARNING)
    flow = InstalledAppFlow.from_client_config(
        client_info, scopes=OAUTH_SCOPES, autogenerate_code_verifier=True
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        timeout_seconds=300,
        prompt="consent",
        login_hint=EXPECTED_USER_EMAIL,
        authorization_prompt_message="Authorize your domain account in the browser: {url}",
        success_message="Consent received. You can close this tab; account and Calendar access are being verified.",
    )
    info = {
        "type": "authorized_user",
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "refresh_token": credentials.refresh_token,
        "scopes": list(OAUTH_SCOPES),
    }
    verified = verified_user_credentials(info)

    # Persist only after grant/identity verification. Calendar access can then be
    # diagnosed without losing the approved grant or requiring repeated consent.
    client = secretmanager.SecretManagerServiceClient()
    version = client.add_secret_version(
        request={
            "parent": f"projects/{PROJECT_ID}/secrets/{OAUTH_SECRET}",
            "payload": {"data": json.dumps(info).encode("utf-8")},
        }
    )
    print(f"Verified {EXPECTED_USER_EMAIL}; saved user OAuth in Secret Manager: {version.name}", flush=True)
    service = build("calendar", "v3", credentials=verified, cache_discovery=False)
    require_calendar_write_access(service, CALENDAR_ID)
    print("Calendar write-access preflight passed. No maintenance events were changed.", flush=True)


if __name__ == "__main__":
    main()
