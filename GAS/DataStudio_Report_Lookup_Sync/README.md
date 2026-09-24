# DataStudio Report Lookup Sync

Apps Script that removes the manual step of mapping Looker Studio report names in
`pccw-internal-virt-agent-uat.Admin.DataStudioReportLookup` (which
`Admin.DataStudioUsage` joins on to fill `looker_studio_report_name`).

## How it works
1. Daily trigger calls the Looker Studio API `assets:search?assetTypes=REPORT`.
2. Lists every report visible to the account running the script (`name` = report id,
   `title` = report name).
3. MERGEs `looker_studio_report_id -> report_name` into `Admin.DataStudioReportLookup`
   (updates renamed reports, inserts new ones, keeps `first_seen_at`).

## API notes (verified live 2026-09-23)
- The Data Studio API must be **enabled** on the quota project
  (`datastudio.googleapis.com` — done on `pccw-internal-virt-agent-uat`).
- Requests **must** include header `x-goog-user-project: pccw-internal-virt-agent-uat`,
  otherwise the call 403s with `SERVICE_DISABLED` against a random default project.
- Response fields: `name` (uuid = `looker_studio_report_id`), `title` (report name),
  `owner`, `assetType`, plus timestamps. Paginated via `nextPageToken`.
- With jjkli@ as the authed account: 56 reports visible; a full pull + MERGE
  backfill was already run against `Admin.DataStudioReportLookup` (57 -> 60 rows).
- 3 report IDs seen in usage were not visible via the API (deleted or unshared
  since Aug 2026): `bd79fb7b…` (was Wanda transcript feedback),
  `4d107f6c…` (was AA Projects / Jira), `75e2bd2d…` (was HD Workload / JIRA HD).
  They were given descriptive `(deleted report - was: ...)` placeholder names on
  2026-09-23 so `DataStudioUsage` shows no blank names. If one of these IDs ever
  reappears in the API, the daily MERGE overwrites the placeholder with the real
  name automatically.

## Setup
1. Create the script at https://script.google.com, paste `Code.js`.
2. **Run as a user who can see all reports** (Looker Studio admin / owner of most
   reports). The API only returns assets that user can access.
3. Project Settings -> tick **Show "appsscript.json" manifest file**, then replace
   the manifest with the `appsscript.json` from this folder (it enables the
   BigQuery Advanced Service and sets the required OAuth scopes, including
   `.../auth/datastudio` — without it the API returns
   `ACCESS_TOKEN_SCOPE_INSUFFICIENT`).
4. Re-authorize: run `syncReportLookup` once, accept the new permission prompt
   (must show a consent screen incl. "View and manage your Data Studio data").
   If no prompt appears, revoke at https://myaccount.google.com/permissions and run again.
5. Run `setupDailyTrigger`.

## Notes
- Unmapped report IDs in `DataStudioUsage` = reports the sync account cannot see
  (owned by others / not shared). Share them or delegate an admin account.
- Schema of the lookup table is unchanged; no edits needed to the view.
