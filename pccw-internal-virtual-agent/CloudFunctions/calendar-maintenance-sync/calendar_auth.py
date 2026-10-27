"""User-only OAuth validation for the maintenance calendar."""

import logging

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

EXPECTED_USER_EMAIL = "jjkli@consoleconnect.com"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
OAUTH_SCOPES = (CALENDAR_SCOPE, EMAIL_SCOPE, "openid")
WRITABLE_ROLES = {"writer", "owner", "writerWithoutPrivateAccess"}
CONSENT_HELP = (
    "Run authorize.py with the approved Desktop OAuth client and consent as "
    f"{EXPECTED_USER_EMAIL}. Save the verified user grant in google-calendar-user-oauth. "
    "Do not grant service accounts Calendar access."
)


class CalendarAuthError(RuntimeError):
    """Calendar authorization failed; no alternate identity may be used."""


def verified_user_credentials(info: dict) -> Credentials:
    if info.get("type") != "authorized_user":
        raise CalendarAuthError("Calendar requires authorized_user OAuth credentials. " + CONSENT_HELP)
    if not all(
        isinstance(info.get(key), str) and info[key].strip()
        for key in ("client_id", "client_secret", "refresh_token")
    ):
        raise CalendarAuthError("Calendar user OAuth refresh credentials are incomplete. " + CONSENT_HELP)

    try:
        # Refresh even when an access token is cached: validate the actual grant,
        # not scopes asserted in a local JSON file.
        credentials = Credentials.from_authorized_user_info(info)
        credentials.refresh(Request())
    except (ValueError, RefreshError, TransportError):
        raise CalendarAuthError("Calendar user OAuth refresh failed. " + CONSENT_HELP) from None

    granted_scopes = set(credentials.granted_scopes or ())
    if not {CALENDAR_SCOPE, EMAIL_SCOPE}.issubset(granted_scopes):
        raise CalendarAuthError(
            "The user OAuth grant lacks Calendar or email consent. "
            "Setting scopes in Python cannot add permissions to an existing grant. " + CONSENT_HELP
        )

    try:
        with AuthorizedSession(credentials) as session:
            response = session.get("https://www.googleapis.com/oauth2/v2/userinfo", timeout=30)
            response.raise_for_status()
            identity = response.json()
    except (RequestException, ValueError, RefreshError, TransportError):
        raise CalendarAuthError("Unable to verify the Calendar OAuth user identity. " + CONSENT_HELP) from None

    if (
        not isinstance(identity, dict)
        or identity.get("verified_email") is not True
        or str(identity.get("email", "")).casefold() != EXPECTED_USER_EMAIL.casefold()
    ):
        raise CalendarAuthError(f"Calendar OAuth must belong to verified user {EXPECTED_USER_EMAIL}.")

    logger.info("Verified Calendar OAuth user: %s", EXPECTED_USER_EMAIL)
    return credentials


def require_calendar_write_access(service, calendar_id: str) -> str:
    try:
        # calendarList is a subscription list, not an access-control check.
        # The events response reports the effective role even for unlisted calendars.
        entry = service.events().list(
            calendarId=calendar_id, maxResults=1, fields="accessRole"
        ).execute()
    except HttpError as error:
        status = error.resp.status
        if status == 404:
            message = (
                "Target calendar does not exist or is not accessible to this user. "
                "Check CALENDAR_ID and sharing with the verified user."
            )
        elif status in (401, 403):
            message = "Calendar access denied. Check OAuth consent, Workspace policy and the user's calendar role."
        else:
            message = "Calendar access preflight failed."
        raise CalendarAuthError(f"{message} HTTP {status}. User: {EXPECTED_USER_EMAIL}.") from None
    role = entry.get("accessRole")
    if role not in WRITABLE_ROLES:
        raise CalendarAuthError(
            f"{EXPECTED_USER_EMAIL} needs writer access to the target calendar; current role: {role!r}. "
            "Owner access is not required."
        )
    logger.info("Calendar write-access preflight passed: user=%s role=%s", EXPECTED_USER_EMAIL, role)
    return role
