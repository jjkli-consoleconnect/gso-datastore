Data Studio Report Name Sync (Apps Script)

Purpose
- Best-effort sync Looker Studio report names from Google Drive into BigQuery lookup table `Admin.DataStudioReportLookup`.
- When Drive metadata is visible, the script resolves friendly names automatically.
- When Drive metadata is not visible, it preserves any existing manual names and keeps syncing report IDs from BigQuery usage.

Main Functions
- `syncLookerStudioReportNamesToBigQuery()`: one sync run.
- `setupDailySyncTrigger()`: creates a daily time-driven trigger for the sync function.

Target BigQuery Table
- Project: `pccw-internal-virt-agent-uat`
- Dataset: `Admin`
- Table: `DataStudioReportLookup`

Deploy with clasp
1. `cd GAS/DataStudio_ReportName_Sync`
2. `clasp create --type standalone --title "DataStudio Report Name Sync"`
3. `clasp push`
4. Open Apps Script editor, run `syncLookerStudioReportNamesToBigQuery` once for authorization.
5. Run `setupDailySyncTrigger` once.
