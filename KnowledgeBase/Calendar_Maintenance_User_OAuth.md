# Calendar maintenance: user-only OAuth

## Identity boundary

All Calendar API calls must use verified user `jjkli@consoleconnect.com`.
Workspace policy blocks external accounts, including service accounts.
Do not grant service accounts Calendar ACLs or domain-wide delegation.

The Cloud Function runtime and Scheduler still have infrastructure service
identities for invocation, Secret Manager and BigQuery. Those identities are
never passed to the Calendar API. A Secret Manager/IAM error must not trigger
an alternate Calendar identity.

## Observed failure (2026-10-27)

The `google-calendar-user-oauth` grant refreshed successfully and identified
the expected verified user, but its granted scopes contained only Cloud
Platform, email, OpenID and SQL login. Calendar requests returned HTTP 403,
reason `insufficientPermissions`. Calendar sharing does not fix missing OAuth
consent. Scopes supplied to a Python credentials constructor cannot expand an
existing grant.

After browser consent, a second problem was confirmed: the configured
`c_241316c19b3773b70476434f03ac62e5a3c8347e7fdcc1a099abb32a4e9bea0d@group.calendar.google.com`
calendar returns 404. The user confirmed the actual target:

- Name: **Remedy Maintenance**
- ID: `c_d2bb391636ca477681527cabaa16d3a60acf512c30530a922f4c4db04c62a86c@group.calendar.google.com`
- Verified user role: `owner`.

The verified Calendar-scoped grant is now stored in
`google-calendar-user-oauth`. Do not repeat browser consent unless verification
fails or a deliberate rotation is required.

## Authorize and store securely

Use an organization-approved **Desktop OAuth client**, owned by the intended
GCP project, with Google Calendar API enabled. Configure the OAuth audience as
Internal for this Workspace organization where applicable. The Workspace
administrator may need to trust the OAuth client and allow its Calendar
scope. External apps in Testing can have short-lived refresh tokens; do not
rely on those for unattended production runs.

From the repository root in PowerShell:

```powershell
py -3 -m venv .venv-calendar-sync
$env:PYTHONPATH = (Get-Location).Path
& .\.venv-calendar-sync\Scripts\python.exe -m pip install -r .\pccw-internal-virtual-agent\CloudFunctions\calendar-maintenance-sync\requirements.txt
& .\.venv-calendar-sync\Scripts\python.exe .\pccw-internal-virtual-agent\CloudFunctions\calendar-maintenance-sync\authorize.py --client-secrets 'C:\path\to\approved-client.json'
```

Create the isolated environment only if it is absent. Set `PYTHONPATH` from the
repository root in each new terminal so local commands use the canonical
repository `shared` package. There is no function-local copy. Deployment still
packages the required shared modules into the runtime ZIP.

In the browser, choose only `jjkli@consoleconnect.com` and approve Calendar
access. The command requests Calendar, email and OpenID scopes and uses a
loopback redirect with PKCE. It refreshes the grant and verifies email before
adding a Secret Manager version, then checks the target calendar's effective
write role. If the calendar check fails, the verified grant remains protected
in Secret Manager for further diagnostics; setup still exits with an error.
No user access/refresh token is written to a local file or printed.
The existing secret must already exist, and the setup operator needs permission
to add a version. The Desktop client JSON is not a user grant: obtain it only for reauthorization
and keep it in an approved protected location outside the repository. The local
client JSON and temporary test environment were removed during cleanup;
the working user grant remains in Secret Manager.

The secret stores only `authorized_user` credentials. Runtime access to the
secret is still required. Rotation must use the same validated setup command;
do not upload arbitrary ADC files or service-account keys.

If consent is blocked by Workspace policy, give the administrator the OAuth
client ID from the approved client configuration and ask them to allow that
client's Calendar scope. Code cannot bypass an administrator's consent policy.

## Verify without syncing

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv-calendar-sync\Scripts\python.exe .\pccw-internal-virtual-agent\CloudFunctions\calendar-maintenance-sync\main.py
& .\.venv-calendar-sync\Scripts\python.exe -m unittest discover -s .\pccw-internal-virtual-agent\CloudFunctions\calendar-maintenance-sync -p test_calendar_sync.py
```

Running the module directly only verifies stored OAuth and Calendar access;
it never invokes the maintenance sync. No secret values should appear in logs.
The deployed authenticated HTTP endpoint also supports `?mode=check-auth`.
It verifies the runtime's secret access and user authorization without querying
BigQuery or creating/updating events. Keep the existing invoker IAM restriction.

- Refresh/scope/identity failure: repeat approved user consent.
- Calendar HTTP 401/403: inspect consent, API enablement and Workspace policy.
- Calendar HTTP 404: check `CALENDAR_ID` and sharing with the verified user.
  The preflight uses the effective role on an events response, not CalendarList:
  a calendar can be accessible without being subscribed in CalendarList.
- Read-only role: grant the user writer access. Owner access is not required.

For end-to-end write verification, obtain approval to create one clearly
labelled test event without attendees, patch it, read it back, and delete
only that event. A successful metadata read alone does not prove event writes.

### Verified deployment (2026-10-27)

- 29 regression tests passed.
- Approved temporary event create, update, read-back and deletion all passed
  using `jjkli@consoleconnect.com`; Meet creation succeeded too.
- ACTIVE revision: `remedy-maintenance-calendar-sync-00016-xix`.
- Deployed `?mode=check-auth`: HTTP 200, `AUTHORIZED`, expected user/calendar.
- Storage API inspection confirmed exactly six deployed runtime source files.
- Bulk maintenance sync was not invoked. Calendar sharing, IAM, runtime
  identity and Scheduler were not changed.
- No Scheduler job in `europe-west2` targets this function. The previously
  documented `remedy-maintenance-calendar-schedule` job returns 404. Daily
  automation is not configured; creating a schedule is a separate action.

## Deployment and sync behavior

Deploy using the function's `deploy.py` after verification. Recreate the local
environment above if needed:

```powershell
$env:PYTHONPATH = (Get-Location).Path
& .\.venv-calendar-sync\Scripts\python.exe .\pccw-internal-virtual-agent\CloudFunctions\calendar-maintenance-sync\deploy.py
```

The command uses Cloud Functions REST APIs and an explicit in-memory six-file
ZIP: runtime modules, requirements, and the canonical repository shared logging
modules plus their package initializer. Credentials, tests and historical
scripts are never included. The operator token comes from the explicitly
selected user's gcloud credential store and is held in memory. Scheduler,
runtime identity and IAM are unchanged.

The previous CLI upload produced a 22-byte empty archive despite listing the
expected source files; Cloud Build then failed with `missing main.py`.
Do not use that CLI packaging path. The REST deployment validates ZIP entries
before upload and reports the operation name for recovery without resubmitting.

`CALENDAR_ID`, `CALENDAR_OAUTH_SECRET`, `TARGET_PROJECT`
and `SYNC_WINDOW_HOURS` are the supported runtime settings.

The sync checks identity, scopes and calendar role before reading BigQuery.
It hashes incident/start into a valid deterministic event ID, supplies that
same ID on insert, and patches existing events without replacing Meet links.
Concurrent create conflicts are resolved by patching the same ID. Per-row
validation/API failures are logged and return HTTP 500 for Scheduler retry;
authorization errors stop the run rather than falling back.

Earlier versions inserted random event IDs. The new IDs cannot automatically
identify those old events: review any pre-existing maintenance events before
enabling production sync. Do not bulk-delete or silently adopt events by title.
