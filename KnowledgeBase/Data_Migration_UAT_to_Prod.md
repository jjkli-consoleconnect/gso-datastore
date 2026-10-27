# Data Migration & Environment Architecture: UAT -> Prod

**Status:** Draft for discussion · **Date:** 2026-10-13 · **Repo:** `c:\dev\gso-datastore` (branch `main`)
**Scope:** Data pipelines and dashboard connectivity between the UAT and Prod GCP projects.

**Execution checkpoint (2026-10-14):** the ten primary source/history tables in §9.3 were seeded as non-live baselines from a common UAT snapshot at `2026-10-14T06:53:21.279Z`. Current Prod destinations are `BMC`, `Jira`, `PagerDuty` and `Training`; the five original Helix targets were subsequently consolidated into BMC (see §8.0). Every target passed an exact full-row comparison including duplicate multiplicities, plus schema, clustering and partitioning checks. Existing targets were not overwritten; existing `BMC.UserList` was left unchanged. The subsequent Training consolidation updated its directly dependent view (see §8.0). The first duplicated pipe, PagerDuty, is enabled for controlled manual validation but unscheduled; see §9.4.1. No UAT checkpoint/state history, scheduled queries or GAS deployments/triggers have been migrated. These baselines need catch-up/final reconciliation before any consumer cutover; they are not continuously refreshed.

> Snapshot: user intends to point all datapipes and dashboards at the **Prod** project, and to use the UAT project only to hold snapshots of Prod data as backup.
> **Hard constraint — no data loss of any kind, under any circumstance.** We will do whatever is necessary to keep every record intact. There is no rollback-less move: no silent truncates, no silent deletes, no unverifiable overwrites. UAT always remains a recoverable restore target, and Prod is only ever touched with verified, idempotent, and reversible changes.

## 1. Proposed goal

- Every datapipe and dashboard in both environments targets **Prod** BigQuery as the single live data source.
- The UAT project is a **read-only consumer** of Prod data: it holds scheduled snapshots of Prod for backup and testing, and does not directly write to Prod.
- Prod is the single source of truth; UAT is a disposable replica used for regression testing and point-in-time backup.

## 2. Environment ownership

| Item | UAT project | Prod project |
|---|---|---|
| GCP project ID | `pccw-internal-virt-agent-uat` | `pccw-internal-virtual-agent` |
| Intent | Snapshot / backup + test only | Live ingestion + dashboards |
| Writes | Snapshot loads only | Ingestion -> BigQuery |
| Readers | Snapshot pipeline only | Datapipes + dashboards |

Datasets referenced across the repo include `GSO`, `wanda_ds`, `AgentDataset` and `Looker`; Prod and UAT each hold their own copies. Prod is the source of truth for the snapshot pipeline.

## 3. Data flow

```
Prod (pccw-internal-virtual-agent)
  |-- datapipes ingest -> BigQuery
  |-- dashboards -> BigQuery (prod)
  |-- snapshot job -> copy tables to UAT

UAT (pccw-internal-virt-agent-uat)
  |-- snapshot loads -> BigQuery (uat)
  |-- test dashboards -> BigQuery (uat)
```

Legend:
- `PROD -> UAT`: one-way snapshot / backup. Never writes to Prod.
- `PROD -> dashboards`: live reads from the authoritative data.
- `UAT -> dashboards`: test reads only.

## 4. Snapshot policy

What to snapshot:
- Full tables that prod-facing dashboards need for regression testing (for example `GSO.JiraTickets` and any table backing a prod dashboard).
- Schedule: align with the ingestion cadence, or daily, and keep enough history to cover common regressions.

Retention:
- Roll-based retention, e.g. keep rolling snapshots for N days (suggested 14 days for backup), then archive to Cloud Storage or delete per a documented rule.

Monitoring and alerting:
- Alert on snapshot job / pipeline run failure.
- Alert when UAT is behind Prod by more than the expected lag tolerance.

Safety rules:
- Snapshot loads are idempotent (MERGE on a key, or insert-if-not-exists).
- Never delete or overwrite Prod tables from UAT.

## 5. Security and IAM

- The snapshot service account needs least-privilege read access on Prod and write access on UAT only.
- Dashboards in each project must be IAM-scoped to that project; do not share service accounts across projects.
- Keep credentials out of the repository.

## 6. Risks and mitigations

| Data loss / irreversible change | No silent truncates or deletes; UAT stays a restore target; every load is idempotent; rollback is always available. |
| Sourcing/recovery failure | If a backup or archive source is missing or corrupt, stop and escalate — never fall back to guessing. |

## 6.1 No data loss required

- The "what/where is missing" question is always answered by comparing UAT and Prod before any write.
- Prod is only touched with verified, idempotent, reversible changes; UAT is the restore fallback and is never cleaned up during cutover.
- Any cutover step that cannot be proven safe against data loss is paused and escalated.

## 7. Checklist before locking in

- [ ] Snapshot schedule validated end-to-end
- [ ] Dashboards moved and validated to point at Prod only
- [ ] Every Prod table has a reviewed clustering design or an approved exception; dashboard performance is measured before cutover
- [ ] IAM least-privilege verified on both projects
- [ ] Retention and cost agreed
- [ ] Snapshot failure monitoring / alerting defined
- [ ] Rollback and recovery runbook updated

## 8.0 Prod dataset layout (proposed)

Business data is organized by source system. Supporting datasets have explicit responsibilities: `Datapipe` for pipeline runtime state, `Admin` for shared administrative metadata, `Staging` for disposable load intermediates, and `Dashboards` for dashboard outputs.

**Layout decision (2026-10-14):** use the proposed source-system layout for migration targets rather than mirroring UAT's `GSO` dataset into Prod. Dataset names are case-sensitive: the proposed `Jira` target is distinct from the existing Prod `JIRA` dataset. Do not modify or remove existing datasets as part of seeding. Exact table mappings, supporting runtime/audit destinations and clustering keys still require review before writes.

**Supporting dataset decision (2026-10-14):** put pipeline progress, checkpoints, batch manifests, repair queues, run logs, processed-message deduplication and durable ingestion-cycle state in `Datapipe`. Reserve `Admin` for shared non-secret configuration, ownership/catalogue metadata and administrative lookups such as `DataStudioReportLookup`. Do not move business reference data to `Admin` merely because it is small, or store credentials there.

**Training consolidation (2026-10-14):** copied the two-row Prod `TrainingData.TrainingData_Gsheet` table into `Training.TrainingData_Gsheet`, preserving its schema. Keep it separate from `Training.TrainingData`, whose schema/source differs. Verified exact full-row contents and unchanged results for the directly dependent UAT `GSO.TrainingData_cleaned` view, then updated that live view and its repo definition to the new path. Preserved the legacy dataset's UAT App Engine service-account reader grant on `Training`. Recent seven-day Prod job history showed manual loads, not an identified automated sheet feeder; future loads must use the new path. With explicit user approval, deleted only the old table and then the empty `TrainingData` dataset after fresh exact-data and zero direct live-view-dependency checks. No pipeline triggers were changed.

**BMC/Helix consolidation (2026-10-14):** BMC and Helix are one source system; use the existing Prod `BMC` dataset for both. Copied all five Prod Helix tables into previously absent BMC targets without overwriting anything. Exact complete-row comparisons, including duplicate multiplicities, found zero differences for all five tables; schemas, descriptions, clustering and partitioning were preserved. Dataset access grants already matched, and existing `BMC.UserList` and `BMC.UserListCleaned` remained unchanged. Dependency checks found no direct Prod/UAT live-view references, Prod routines, EU transfer configurations or Prod function environment variables targeting this Helix dataset. Seven-day Prod jobs showed only migration seed/verification work, not active ingestion writers. After explicit deletion approval and fresh dependency/unchanged-table checks, deleted only the five verified originals and then the empty Prod `Helix` dataset. UAT source tables and deployments remain unchanged. Future migrated writers must target BMC; historical seed manifests retain their original paths for audit and must not be resumed against the retired Helix dataset.

| New dataset | Source of data | Contents (tables) |
|---|---|---|
| `Jira` | Jira | `JiraTickets`, `JiraChangelog`, `JiraComments` |
| `Workflows` | Jira → Helix sync | `jira_to_helix_sync`, `jira_to_helix_comment_sync`, `jira_to_helix_close_dup_sync` |
| `PagerDuty` | PagerDuty | `PagerDutyIncidentData` |
| `Linxa` | Linxa | existing Linxa tables |
| `Confluence` | Confluence | existing Confluence tables |
| `SubCableEvents` | SubCableEvents | existing SubCableEvents tables |
| `Training` | training | `TrainingData`, `TrainingData_Gsheet` |
| `HubSpot` | HubSpot surveys | `HubspotRemedyClosureSurvey`, `HubspotSCNFeedback` |
| `Gsheet` | live Google Sheets sources | external `CustomerSuccessTracking`, `ICAIR` |
| `Verification` | verification performance reports | `VerificationVerifierPerformance`, `VerificationPRRequesterPerformance` |
| `BMC` | BMC Helix ticketing + service inventory | `UserList`, existing `UserListCleaned` view, `HelpDeskAllNOC`, `WorkLogAllNOC`, `SHRPeople`, `SHRPeople_History`, `SRInventory` |
| `Datapipe` | pipeline operations | Jira progress/batch tables, ticket nightly state/keys/repairs, `PipelineRuns`, `ProcessedPubSubMessages`, `SHRPeople_Cycle`, `SHRPeople_CycleFiles` |
| `Admin` | shared administration | non-secret configuration, ownership/catalogue metadata, administrative lookups; no tables added to the seed batch without inventory review |
| `Staging` | temporary ingestion intermediates | disposable per-run load/merge tables; not seeded from UAT |
| `Dashboards` | dashboards | derived/aggregated views powering dashboards |

Keep table names unchanged for traceability; retain source-specific prefixes on runtime tables. Business workflow ledgers stay in `Workflows`, even when used for idempotency, because they record external business actions. Backups and mirrors stay in UAT. Create only datasets required by the approved batch, with explicit ownership, location and least-privilege access. Use `EU` for targets of the inventoried EU sources; runtime state is durable and must not inherit disposable staging expiration.
## 8. Datapipe & Dashboard Inventory

Data-pipes run as Cloud Functions. Dashboards are the BigQuery views
(Dashboards in Prod, Looker/Mirror in UAT). The tables below are the
reference points for the prod-first migration.

### 8.1 Datapipes — UAT (`pccw-internal-virt-agent-uat`)

| CloudFunction | Source system | Reads | Writes |
|---|---|---|---|
| `bq_hdwl` | BMC Helix ticketing | `BMC.HelpDeskAllNOC`, `BMC.WorkLogAllNOC`, snapshot feeds | `BMC.HelpDeskAllNOC`, `BMC.WorkLogAllNOC` (staging: `Staging.*`) |
| `gmail_checker` | Gmail / Pub/Sub | Gmail only | Pub/Sub topics |
| `hdwl_daily_rerun` | BMC Helix | `BMC.HelpDeskAllNOC`, `BMC.WorkLogAllNOC`, `PipelineRuns` | same as `bq_hdwl` |
| `pagerduty_incident_data` | PagerDuty | PagerDuty API + Insights exports | `PagerDuty.PagerDutyIncidentData` |
| `pipeline_report` | internal | `PipelineRuns` | Slack/email only |
| `shr_people` | BMC Helix | `BMC.SHRPeople_History`, staging cycle tables | `BMC.SHRPeople`, `BMC.SHRPeople_History`, `PipelineRuns`, staging cycle tables |
| `snapshot_reports` | snapshot | `Snapshot.*` | `Snapshot.PipelineRuns` + reports |
| `SRInventory` | SR inventory | `SRInventory` | `SRInventory`, `PipelineRuns` |
| `training_data` | training | CSV from Gmail | `Training.TrainingData` (truncate/replace), `PipelineRuns` |
| `bq_bmc_user_list` | `BMC` | `BMC.UserList` (UAT + Prod) | `BMC.UserList` (UAT + Prod) |
| `mss-to-remedy-create-uat` | Workflows | `Workflows.*` ledgers | `Workflows.*` ledgers + Helix |

### 8.2 Datapipes — Prod (`pccw-internal-virtual-agent`)

| CloudFunction | Source system | Reads | Writes |
|---|---|---|---|
| `JiraTicketsNightly` / deployed `jira-tickets-nightly` (`delta` mode; audit `GCP - JiraTicketsNightly`) | Jira | Jira API + saved delta progress | `Jira.JiraTickets`, `Jira.JiraTickets_progress`, shared ticket runtime tables + `PipelineRuns` |
| Same `jira-tickets-nightly` function (`maintenance` mode; audit `GCP - JiraTicketsWeekly`) | Jira | Jira API + ticket inventory, saved snapshots and repair candidates | `Jira.JiraTickets`, shared ticket runtime tables + `PipelineRuns` |
| `JiraTickets`, `JiraChangelogs`, `JiraComments`, `JiraChangelogsNightly`, `JiraCommentsNightly` | Jira | Jira API | Jira datasets + `PipelineRuns` |
| `mss-to-remedy-create-prod` | Workflows | `Workflows.*` ledgers | `Workflows.*` ledgers + Helix |
| `hdwl-softdelete-prod` | BMC soft-delete CSV via shared UAT Pub/Sub topic | Explicit report IDs, `BMC.HelpDeskAllNOC`, UAT Gmail secret | Listed existing rows' `Soft_Delete_*` fields; `Datapipe.PipelineRuns`; Gmail `ArchivedReports` label |
| `DataCatalogue` | metadata | Prod BigQuery metadata | Confluence page |

**Jira ticket split (deployed October 14, 2026):** nightly delta catch-up starts
daily at 23:45 Hong Kong; weekly inventory, historical repairs and soft-delete
reconciliation start Saturday at 02:00 Hong Kong. Each mode has its own
resume-only Scheduler job and separate run/audit identity, but shares one
Cloud Function. The ten-minute ticket sync and comments/changelog jobs are unchanged.

The `Jira.*` destinations above describe the **proposed migration layout**, not
the current ticket target. Both ticket modes are deployed in Prod but still
write to `pccw-internal-virt-agent-uat.GSO`. Their shared durable runtime tables
are `JiraTickets_nightly_state`, `JiraTickets_nightly_keys` and
`JiraTickets_nightly_repairs`; `RunMode` separates their checkpoints.
Migration must preserve these tables and `JiraTickets_progress`, including
unfinished runs, saved cursors, snapshots, repair candidates and accumulated
metrics. The existing combined sweep was adopted by weekly maintenance without
restarting; unfinished maintenance may therefore continue before the next Saturday.
See the canonical [ticket recovery and scheduling runbook](JiraTicketsNightly_Recovery.md).

### 8.3 Dashboards (BigQuery views)

| Project | Dataset | Views (dashboards) |
|---|---|---|
| Prod | `Dashboards` | `CCAIInsightsExtracted`, `CCAI_Dialogflow`, `DialogflowExtracted`, `KMActivityLog`, `vw_kms_agent_consumption_activity`, `vw_knowledge_ingestion_monitor`, `WandaTranscript` |
| UAT | `Looker` | `CCAS*`, `CCPROV`, `CommKPI`, `HDWL_combined`, `HD_CarrierVendor`, `helpdesk`, `LSR_JIRATickets`, `MailboxCombined`, `MTTR`, `Outstanding-Escalation-Snapshots`, `OutstandingSnapShift`, `ProjectTracking`, `RFO`, `vw_centre_operations_circuit_availability`, `WLShift`, `WLT`, `WLTCreationClosure`, `WorkLog` |
| UAT | `Mirror` | `CostItem` |

### 8.4 Open items (no `*.md` docs — verify against `main.py`)

- `gmail_checker` — no BigQuery (Gmail -> Pub/Sub).
- `hdwl_daily_rerun`, `shr_people`, `SRInventory`, `training_data`, `bq_bmc_user_list` — confirmed against `main.py` (see table).
- Jira-related Prod functions — verify target `Jira.*` tables against each `main.py`.

### 8.5 Source connectors (GAS / scripts / sync)

The CloudFunctions track the data, but the *source data* is ingested by the connectors below. These were missing from the earlier list and must be included in the prod-first cutover.

**Scope correction from owner (2026-10-15):** the historical connector inventory
below is not a list of active scheduled jobs. Do not duplicate archived or manual
imports merely because their source exists in the repository.

| Apps Script | Owner-confirmed scope / verified status |
|---|---|
| `DataStudio_Report_Lookup_Sync` | Live ID `1n2ZQ2OApCQiSq1lu6dibk57zRYrF70aNxnVVuSQw6ws2wbb08efJ85BR`; deployed and re-read verified. Fetches reports once, writes both UAT and Prod `Admin.DataStudioReportLookup`, keeps UAT quota project and one error notification. Existing daily 02:00 trigger installer unchanged; installed triggers remain unverified |
| Training sheet feeder | Live ID `1lalQ4XsojMFuQh8xVDiXZTuqYriQnw-yB1ER2X73d-YhkN9ZUCo-LBzz`; deployed and re-read verified. `Sync BQ > Sync Now` now writes Prod `Training.TrainingData_Gsheet` with EU job routing. Still a manual active-sheet `WRITE_TRUNCATE` import; no sync was invoked |
| `HubSpot to BQ Sync` | Live ID `1i3gyM6Kaq5_BsScy3_n5dDCpVSiZegCMj7sFwj4o6RMvKAKSw4ZtI3E9`; deployed and re-read verified. One conversion/read per survey, writes UAT `GSO` and Prod `HubSpot`, with Prod temporary tables in `Staging`. Existing monthly first-day 02:00 installer unchanged; installed triggers remain unverified |
| `VerificationTeamDataPipeline` | Live ID `1gr6P1u28S8hpsnKr_n-Dg98hRWU6aKIYzDO7bsEwEioQu1PqF5az53jU`; deployed and re-read verified. Reads each report once, writes UAT `GSO` and Prod `Verification` before marking the shared file processed; Prod temporary tables in `Staging`. Existing entry points retained; source has no trigger installer and installed trigger ownership remains unverified |
| `Gmail_to_BQ_BMC_User_List` | Live ID discovered: `1hBx0ydGjoOKCxjXMWtPNmxa2eiuj11nJJjJJQbyuNArY8_nOnNhSz-XE`; live source pulled. Archive candidate, not archived by this migration. GAS duplicates both destinations and defines a Sunday 10:00 trigger installer; actual installed triggers still need owner inspection. Live Cloud Function `process-bq-bmc-user-list-email` is active and its pinned deployed source writes both Prod and UAT `BMC.UserList`. Latest verified audit: `SUCCESS`, 888 combined rows, 2026-10-14 20:04:11 UTC; both tables contain 444 rows with zero exact full-row/duplicate differences |
| `Gmail_to_BQ_HDWL`, `Gmail_to_BQ_GSO_SHRPeople`, `Gmail_to_BQ_SHRPeople`, `Gmail_to_BQ_HelpDesk`, `Gmail_to_BQ_JIRAJoin`, `support_at_consoleconnect_com`, `CostItemExpiration` | Owner says archived; excluded from migration |
| `Drive_to_BQ_HDWL` | Manual importer; owner requested destination updates, not a duplicate schedule |
| `Gmail_to_BQ_WorkLog` | Listed live as archived; excluded from migration |
| `Drive_to_BQ_WorkLog`, `Drive_to_BQ_manual_WorkLog` | Owner confirms no longer used and requested archival. Repo copies moved to `ARCHIVED_` folders; excluded from migration. Live rename attempted via Drive API but denied by clasp OAuth app file-write scope; live projects/source remain unchanged. No triggers were inspected or disabled |

The installed VS Code GAS extension and `clasp` connection were found.
`clasp list --noShorten` failed when refreshing its existing OAuth credentials
with `invalid_grant` / `invalid_rapt` (Google requires reauthentication).
The active gcloud account is authenticated, but direct Apps Script content API
reads for both supplied IDs returned HTTP 403 with
`ACCESS_TOKEN_SCOPE_INSUFFICIENT`, not evidence of missing script sharing/IAM.
Reconnect the existing clasp account with `clasp login`; do not broaden cloud IAM
or ask for more IDs to work around the expired Apps Script session. No live GAS
source, properties or triggers were changed. Archive the BMC GAS copy only after
its actual script identity and owner-installed triggers are checked; retain the
working Cloud Function.

**Connection restored (2026-10-15):** after the user reauthenticated, `clasp list
--noShorten` succeeded and discovered 40 accessible scripts. Both supplied scripts
and the BMC GAS script were cloned read-only into session storage, leaving the
repository root clasp configuration and live source unchanged. The source-access
blocker is resolved; installed trigger ownership remains a separate verification.
Discovery also identified `HubSpot to BQ Sync`
(`1i3gyM6Kaq5_BsScy3_n5dDCpVSiZegCMj7sFwj4o6RMvKAKSw4ZtI3E9`)
and the known verification pipeline; inspect their live code before defining
remaining connector scope. No more IDs are required for those discovered scripts.

**Manual WorkLog retirement:** preserve the two legacy sources in
[ARCHIVED_Drive_to_BQ_WorkLog](../GAS/ARCHIVED_Drive_to_BQ_WorkLog/) and
[ARCHIVED_Drive_to_BQ_manual_WorkLog](../GAS/ARCHIVED_Drive_to_BQ_manual_WorkLog/).
Do not create Prod `BMC.WorkLog` or `BMC.WorkLog2` for these retired scripts.
The live IDs are respectively
`1UxRILg8ycEysvRyqTYfRIxSu6kJd3dLdxu5dCyeSazVVNt471ey_ShCq` and
`16xEPmJ3A75CoILJUEtAbkirPl_qT2uALOTNnk6xr9HsMhXWGixyrp122`.
The intended live display names are `ARCHIVED_Drive > BQ - WorkLog` and
`ARCHIVED_Drive > BQ manual - WorkLog`. Drive rejected the rename because the
current clasp OAuth app has not been granted write access to these files;
Apps Script content-read access alone does not permit Drive metadata writes.
Local archival is complete; live renaming/owner trigger checks remain outstanding.

**GAS destination rollout (2026-10-15):** canonical active assets now live under
[Prod GAS](../pccw-internal-virtual-agent/GAS/); lookup/verification were moved
from their legacy top-level GAS locations rather than leaving two editable copies.
Live baselines were checked for concurrent edits immediately before each Apps
Script content update. Each resulting live source was re-read and matched exactly;
manifests, OAuth scopes, handler names, Drive source/archive folders, script
properties and installed triggers were not changed.

Four previously absent targets were seeded from a common UAT snapshot without
overwriting existing tables. Exact full-row comparison, including duplicate
multiplicity, and schema/layout checks passed:

| Prod target | Rows seeded | Exact differences | Layout |
|---|---:|---:|---|
| `HubSpot.HubspotRemedyClosureSurvey` | 43 | 0 | Daily `submission_timestamp` partition; `record_id,srno,incid` clustering |
| `HubSpot.HubspotSCNFeedback` | 192 | 0 | Daily `submission_timestamp` partition; `record_id,srno,survey_name` clustering |
| `Verification.VerificationVerifierPerformance` | 1,139 | 0 | Existing approved small-table unclustered exception |
| `Verification.VerificationPRRequesterPerformance` | 1,259 | 0 | Existing approved small-table unclustered exception |

HubSpot now stages using the actual target field types, including string record
IDs and nullable timestamps, instead of first-row type guessing. Excel conversion
uses the enabled Drive v3 service's supported MIME-type conversion. Each destination
is attempted independently; any failed write fails the overall execution rather
than logging a successful run. Temporary BigQuery tables expire after one hour
and are cleaned up explicitly.

Verification keeps the existing per-report-date transaction. Its new
`verification_report_prod_processed_md5` Drive property is written only after
both destinations succeed. A legacy UAT-only checksum does not skip the report:
the next execution replays it idempotently to both destinations, then records
the dual-write marker. This covers files modified around the seed snapshot and
avoids permanently skipping Prod history. Header-only reports fail explicitly
instead of deleting the month's records. No report-date replacement or manual
sheet import was invoked during deployment.

Validation: focused Node mock regression tests cover dual-write routing, one
source read, independent destination failures, cleanup, processed-file markers,
the Training menu/destination and unchanged trigger handlers. Actual BigQuery
dry-runs passed for both environments' generated lookup/survey MERGEs and
verification DELETE/INSERT statements; these dry-runs changed no data.
They validate query/schema compatibility, not a successful scheduled source run.
The Apps Script process-history API returned insufficient permission with the
current clasp OAuth scopes. Therefore no installed schedule, trigger owner or
post-deployment scheduled execution is claimed as verified. Retain existing
triggers, check their owners' Prod write access, and observe the first successful
dual-write executions before calling these connectors stable.

Tools: [seed targets](../Temp/UAT_to_Prod_Migration/migrate_gas_sources.ps1),
[deploy/read-back](../Temp/UAT_to_Prod_Migration/deploy_gas_destinations.cjs),
[query/layout validation](../Temp/UAT_to_Prod_Migration/validate_gas_queries.cjs),
and [regression tests](../Temp/UAT_to_Prod_Migration/test_gas_destinations.cjs).
Deployment requires the explicit session baseline directory; it does not use or
overwrite the root clasp configuration. Use `--verify-only` for subsequent
read-back checks; do not rerun initial deployment against a stale baseline.

**Owner runtime confirmation (2026-10-15):** supplied verification execution
logs show matched reports written to both UAT and Prod and execution completed.
Owner subsequently confirmed the next run skipped unchanged files. Owner also
confirmed `DataStudio_Report_Lookup_Sync` writes both destinations. These are
owner-observed runtime confirmations, not API-based installed-trigger audits.
HubSpot's first live dual-write execution remains unconfirmed.

**Second lookup inspected live:** `DataStudio Report Name Sync`, ID
`1RRd-XT4S7QFcgVcsiTheYBwlSryOw5PXIRCEp6P5weM7IOcRo4kXyYB1`,
is an overlapping implementation, not an identical copy. It reads up to 500
recent distinct report IDs from UAT `Admin.DataStudioUsage`, resolves titles
through Drive, and writes only UAT `Admin.DataStudioReportLookup`. Its source
defines a daily 03:00 trigger installer; actual installed triggers remain unknown.
Unresolved names preserve existing names but new IDs can be inserted with blank
names and null first/last-seen timestamps. The manifest enables Drive v3 while
the listing code uses v2 `items/title/maxResults`, a discovery compatibility issue.
The canonical dual-write lookup instead lists reports using the Data Studio API,
writes both projects and maintains first/last-seen timestamps. Do not add a second
Prod writer blindly. No changes were made to this second script or its triggers;
retain or retire it only after deciding whether usage-ID fallback is needed.

**Owner scope update (2026-10-15 10:36 HKT):** owner confirms the old
`DataStudio Report Name Sync` is now archived. Exclude it from migration and keep
`DataStudio_Report_Lookup_Sync` as the canonical lookup writer. This is an
owner-reported archival; removal of any installed trigger was not independently
verified. Verification dual-write/unchanged-file skipping and canonical lookup
dual-write are owner-confirmed. Owner considers GAS ready; HubSpot's first live
dual-write execution remains unconfirmed in the evidence available here.

**HubSpot scope correction (2026-10-15 10:37 HKT):** owner confirms HubSpot GAS
is archived because the repository Python loader handles these surveys. Exclude
HubSpot GAS from active migration and scheduled-run validation; seeded Prod tables
remain in place. The replacement
[Python loader](../BigQuerySync/load_hubspot_surveys.py) currently defaults to
UAT `GSO` and accepts explicit `--project` and `--dataset` overrides. Its actual
invocation/schedule and Prod writes are not yet verified. Archiving GAS therefore
does not establish that the Python ingestion has migrated to Prod.

**HubSpot Python loader update:** owner approved keeping both destinations during
parallel validation. The [loader](../BigQuerySync/load_hubspot_surveys.py) now
defaults to Prod `HubSpot` plus UAT `GSO`, prepares each workbook once and attempts
both writes. A logged destination failure causes a non-successful command exit.
Existing VS Code load/dry-run tasks inherit these defaults without changes.
`--single-destination` disables the additional UAT write; `--project`/`--dataset`
still select the primary destination. Repeated UAT targets are deduplicated.
Temporary loads use EU `Staging` with one-hour expiration and explicit cleanup.
`--dry-run` performs file validation only, with no BigQuery client or table writes.
The loader's existing target partitioning/clustering and record-ID MERGE are
retained. Local tests include real CSV dry-runs for both survey types; a live
Python ingestion and any external invocation/schedule still need confirmation.

| Connector | Type | Feeds dataset |
|---|---|---|
| Gmail_to_BQ_HDWL / Drive_to_BQ_HDWL | source import | `BMC.HelpDeskAllNOC` |
| Gmail_to_BQ_WorkLog / Drive_to_BQ_WorkLog | source import | `BMC.WorkLogAllNOC` |
| Gmail_to_BQ_GSO_SHRPeople / Gmail_to_BQ_SHRPeople | source import | `BMC.SHRPeople` (+ `_History`) |
| Gmail_to_BQ_BMC_User_List | source import | `BMC.UserList` |
| Gmail_to_BQ_*_Escalation / Outstanding snapshots | backup snapshots | `Backups` (daily) |
| load_hubspot_surveys.py (BigQuerySync) | monthly survey load | `HubSpot` (surveys) |
| Jira → Helix webhook functions (mss-to-remedy-create-prod/uat) | real-time sync | `Workflows` + Helix |

### 8.6 Backup / restore datasets (UAT) — "backup snapshots"

**IMPORTANT — do not confuse the two kinds of "snapshots" in this repo:**

- "Dashboard snapshots" → stored in **Prod** (in the `Dashboards` dataset). These power the dashboards.
- "Backup snapshots" → stored in **UAT** (these `Backups`/`Mirrors` below). These are backup copies of Prod, used only for recovery/testing.

`Backups` and `Mirrors` live in the **UAT** project — they are the backup and restore stores for Prod, not Prod datasets. Do NOT add them to the Prod dataset layout (§8.0).

- `Backups`: daily point-in-time copies of Prod data (e.g., `RemedyEscalationSnapshot`, `RemedyOutstandingSnapshot`, `PipelineRuns`).
- `Mirrors`: mirrored copies of Prod data (e.g., `CostItem`) for testing without affecting Prod.

UAT scheduled queries that save backup snapshots must:
- Read **Prod** as the source of truth.
- Write only into UAT `Backups`/`Mirrors`.
- **Never** write to Prod.

Run UAT backup queries in parallel with Prod writes for consistency; they must never disrupt Prod.
## 9. Safe Migration Procedure (prod-first, zero-disruption)

- [ ] UAT scheduled queries that save snapshots / mirrors: confirm they only read Prod and write to UAT `Snapshot`/`Mirror` (never to Prod).
### 9.1 Principles

- **Baseline first, migrate second.** Never write Prod before you have verified what is already there.
- **Parallel run.** Keep old UAT pipes/schedulers running in parallel through cutover so no data is lost or suddenly dropped. The owner-approved AI/translation-only exception in section 9.6.3 moves paid writers instead of paying for duplicate inference.
- **Toggle, don't cut.** Prefer a runtime `TARGET_PROJECT` env var over rewriting code; flip the env var instead of redeploying logic.
- **Rollback inside minutes.** If a phase misbehaves, flip back; there is no rollback-less move.

### 9.2 Pre-flight checklist

- [ ] Sign-off from the operations team and a data owner.
- [ ] Decide the "source of truth" per table (which project truly owns/buys it).
- [ ] Baseline each critical table: `COUNT(*)`, key set, and sample rows between UAT and Prod.
- [ ] Inventory scheduled queries / Cloud Scheduler jobs and their project IDs.
- [ ] Include all four shared-function ticket jobs: `jira-tickets-nightly-scheduler`, `jira-tickets-nightly-resume`, `jira-tickets-weekly-scheduler` and `jira-tickets-weekly-resume`. Verify their mode payloads, schedules and OIDC identity; migrate both modes and durable runtime state together, without two environments advancing the same sweep.
- [ ] Inventory dashboard/report connections (Dashboards/Looker) and their dataset references.
- [ ] Review every target table's partitioning and ordered clustering keys against actual dashboard queries; record exceptions and agree dashboard latency targets (see §9.2.1).
- [ ] Freeze a low-traffic window and notify operations in advance.

### 9.2.1 Table clustering & dashboard performance gate

**Clustering is required by default for all eligible Prod tables, not just newly copied source tables.** Review existing tables, staging/runtime tables and materialized dashboard tables too. Record an owner-approved exception for unsupported objects or tables where clustering has no demonstrated benefit (for example, small control tables). Logical views cannot be clustered; optimize their underlying tables.

- Choose up to four supported top-level, non-repeated clustering columns from actual dashboard filter patterns. Column order matters: prioritize frequently used, selective filters and verify that dashboard queries use the leading keys. Do not apply one generic key list to every table or assume clustering alone speeds up every join or aggregation.
- Review partitioning separately. For large time-based tables, use a suitable date/time partition where justified and ensure dashboard date filters prune partitions; clustering then prunes blocks within the selected partitions.
- Record the target partitioning, ordered clustering keys, representative dashboard queries and exception rationale per table in the migration inventory. Define new target tables with this layout before seeding; verify existing tables rather than blindly inheriting UAT settings.
- A direct table copy preserves source layout; it does not redesign clustering. If a different layout requires rebuilding a populated table, use a separate destination, validate all data and coordinate writes before switching consumers. Never destructively replace a live table to add clustering.
- Verify the physical layout after seeding and after a full pipeline refresh. Copy, table recreation and truncate/replace paths must preserve the intended partitioning and clustering. Changing clustering metadata alone is not proof that historical data has been reorganized.
- Benchmark representative dashboard filters and date ranges against comparable data and freshness before cutover. Record bytes processed, slot milliseconds, query elapsed time and end-to-end dashboard load time over repeated runs; distinguish cached from uncached results.
- Cutover requires correct results and the agreed dashboard latency targets, with no unacceptable regression. Clustering improves query scan efficiency when filters allow block pruning; it does not guarantee faster ingestion or dashboard rendering.

#### Clustering decisions (2026-10-14)

Retain existing UAT clustering keys in their current order and existing partitioning for the seed batch. For previously unclustered tables, the following user decisions apply; verify exact column names, types and supported clustering eligibility against live schemas before DDL.

| Prod target | Ordered clustering keys / decision | Status |
|---|---|---|
| `Jira.JiraTickets` | `Key`, `Resolved`, `Project` | User-selected; live schema validated and seeded target verified |
| `BMC.SHRPeople_History` | `SRNo`, `Product_Family`, `SR_Status` | User-selected; live schema validated and seeded target verified |
| `Datapipe.JiraTickets_progress`, `Datapipe.JiraChangelog_progress`, `Datapipe.JiraComments_progress` | `Project`, `WindowStart`, `WindowEnd` | Seeded and exactly verified; this does not add partitioning |
| `Datapipe.JiraTickets_nightly_keys` | `Project`, `RunId`, `Key` | User-approved; seeded completed-run contents and verified layout |
| `Datapipe.JiraTickets_nightly_repairs` | `Project`, `RunId`, `RepairIndex` | User-approved; seeded completed-run contents and verified layout |
| `Datapipe.JiraComments_progress_batches`, `Datapipe.JiraChangelog_progress_batches` | `Project`, `WindowStart`, `WindowEnd` | User-approved; seeded completed-window contents and verified layout |
| `Datapipe.ProcessedPubSubMessages` | `pipeline_name`, `message_id` | Created for isolated Prod consumers and verified |
| `Datapipe.SHRPeople_Cycle` | `SourceFile`, `SRNo` | Created for isolated Prod cycle accumulation and verified |
| Verification connector tables | Leave unclustered for now | User-approved temporary exception; connector ownership and destination still require verification |
| `BMC.UserList`, `Datapipe.SHRPeople_CycleFiles`, `Datapipe.JiraTickets_nightly_state` | Leave unclustered | User-approved small-table exception (2026-10-14); observed counts: 444, 12 and 75 rows respectively; review if size or access patterns change |

The remaining runtime layouts now have explicit keys or the approved small-table exception. Small-table exceptions affect physical layout only; they do not exclude data from migration or waive safety checks.

### 9.3 Step 1 — Reconcile data into Prod (only where Prod is missing/stale)

**First-step scope:** seed physical source/ingestion tables and their history only, plus the durable runtime/audit state needed for pipeline continuity. Do not copy logical views, materialized dashboard outputs, backup/mirror datasets, old repair copies or disposable run-scoped staging tables. Preserve genuinely durable in-flight staging state (for example, `Staging.SHRPeople_Cycle` together with `GSO.SHRPeople_CycleFiles`) through a coordinated handover.

The source-system dataset layout below is proposed, not a statement of the live layout. Approve exact source-to-target dataset/table mappings before creating or loading any Prod object, including dataset-name casing and handling existing Prod-owned data.

Primary source/history mappings for the selected layout (table names unchanged):

| UAT source | Proposed Prod destination |
|---|---|
| `GSO.HelpDeskAllNOC`, `GSO.WorkLogAllNOC` | `BMC.HelpDeskAllNOC`, `BMC.WorkLogAllNOC` |
| `GSO.SHRPeople`, `GSO.SHRPeople_History`, `GSO.SRInventory` | Same table names in `BMC` |
| `GSO.JiraTickets`, `GSO.JiraChangelog`, `GSO.JiraComments` | Same table names in `Jira` |
| `GSO.PagerDutyIncidentData` | `PagerDuty.PagerDutyIncidentData` |
| `GSO.TrainingData` | `Training.TrainingData` |
| `BMC.UserList` | Existing `BMC.UserList`; reconcile only if comparison shows a difference |

Supporting state mappings (table names unchanged):

| UAT source | Proposed Prod destination |
|---|---|
| `GSO.JiraTickets_progress`, `GSO.JiraTickets_nightly_state`, `GSO.JiraTickets_nightly_keys`, `GSO.JiraTickets_nightly_repairs` | Same table names in `Datapipe` |
| `GSO.JiraChangelog_progress`, `GSO.JiraChangelog_progress_batches` | Same table names in `Datapipe` |
| `GSO.JiraComments_progress`, `GSO.JiraComments_progress_batches` | Same table names in `Datapipe` |
| `GSO.PipelineRuns`, `GSO.ProcessedPubSubMessages` | Same table names in `Datapipe` |
| `Staging.SHRPeople_Cycle`, `GSO.SHRPeople_CycleFiles` | `Datapipe.SHRPeople_Cycle`, `Datapipe.SHRPeople_CycleFiles` |

Jira progress/checkpoint tables must move with the Jira writers. Preserve the SHRPeople cycle/file-state relationship and processed-message state before handover. UAT workflow ledgers must not overwrite existing Prod workflow ledgers: their external Helix actions belong to different environments. Additional source connectors (including HubSpot and verification imports) need confirmed ownership and target mappings before joining the copy batch.

Separating business tables from runtime state requires independently configured data, runtime and staging destinations, not just a `TARGET_PROJECT` toggle. Before enabling Prod writers, update and test every relevant table reference in pipeline code, shared logging/helpers, resume checks, reporting and scheduler automation. Existing deployments keep their current destinations until their coordinated handover; no two environments may advance the same runtime state. Initial state copies are baselines, not permission to start a second writer; reconcile final checkpoints after quiescing the old writer.

Under the new layout (see §8.0), source-system datasets hold business data; `Datapipe`, `Admin` and `Staging` hold supporting objects, and `Dashboards` holds dashboard outputs. Views and dashboard migration remain outside the first seed batch.

For each critical table:

1. [ ] Baseline: read-only compare of `COUNT(*)` and key set between UAT and Prod.
2. [ ] If Prod is missing or stale, load idempotent data from UAT/source into Prod.
   - Verify the target partitioning and clustering design from §9.2.1 before loading; after loading, confirm the resulting table still has that layout.
   - `WRITE_TRUNCATE` ONLY for a fresh full load, and only after you have verified the new load from a full dry-run.
   - `MERGE` with a key + timestamp guard for incremental loads — never delete source rows.
3. [ ] Re-check `COUNT(*)` and spot-check sample keys against UAT BEFORE declaring it done.
4. [ ] Snapshot Prod before the first large load and keep a short restore window.
5. [ ] Keep UAT intact at all times: UAT is the restore fallback, never the thing being cleaned up.

### 9.4 Step 2 — Repoint one datapipe at a time (parallel run)

For each datapipe:

1. [ ] Snapshot Prod's current state (table + recent job logs).
2. [ ] Add/verify a runtime `TARGET_PROJECT` env var. Do **not** hard-code the project change into logic.
   - Configure business-data, `Datapipe` runtime/audit and temporary staging datasets separately; verify all readers and writers use the approved mappings.
3. [ ] Deploy the pipe and run it in **validation mode** (read from UAT to compute expected output, but commit nowhere).
4. [ ] Compare the pipe's output against Prod-side expectations (row counts + sample keys).
   - Verify a full refresh preserves the target table's partitioning and ordered clustering keys, including any truncate/replace or table recreation path.
5. [ ] Once it matches, flip the runtime target to **Prod** and enable its scheduler.
6. [ ] Monitor `N` consecutive runs (3 full runs + 1 catch-up): errors, row counts, latency.
7. [ ] Only then disable the old UAT pipe / scheduler job.

- Keep old ingestion running until its coordinated handover. Parallel validation must use isolated destinations and checkpoints. Do not start a second Gmail poller that changes shared labels, or replay external Helix actions/notifications. For stateful or side-effecting pipes, use read-only validation, controlled fan-out where supported, or a single-writer handover rather than two active consumers.

### 9.4.1 First Prod pipe and controlled activation checkpoint (2026-10-14)

- Prod `pagerduty-incidents-sync` is deployed in `europe-west2`, Python 3.12, with UAT's existing 512 MiB memory and 540-second timeout. Concurrency and max instances are both capped at one.
- The [Prod-owned source and deployment scripts](../pccw-internal-virtual-agent/CloudFunctions/pagerduty_incident_data/README.md) target `PagerDuty.PagerDutyIncidentData`, `Datapipe.PipelineRuns` and disposable `Staging` intermediates. The UAT implementation/deployment is unchanged.
- Created EU `Datapipe` and `Staging` datasets and an empty `Datapipe.PipelineRuns` matching UAT's schema, clustering and partition layout. No UAT run history/checkpoints copied.
- Dedicated `pagerduty-sync-runtime` has BigQuery job-user access and dataset writer grants on these three datasets only. Dedicated `pagerduty-scheduler-invoker` has invoker access on this Cloud Run service. With explicit user approval, `jjkli@consoleconnect.com` received OpenID Token Creator on that invoker account only for live verification.
- Initial disabled verification returned authenticated HTTP 503 with `status=disabled`; anonymous invocation returned HTTP 403. The disabled guard remains available through the default deployment. With user approval, the function was subsequently redeployed with `PIPELINE_ENABLED=true` for one controlled manual run. No Prod PagerDuty Scheduler job exists.
- Four focused no-network regression tests pass, covering disabled/invalid flags, all run-log destinations, separate staging and unchanged target MERGE destination. Cloud Build successfully built the pinned dependencies and started the service.
- With explicit user approval, UAT `pagerduty-api-token` enabled version 2 was copied in memory to Prod `pagerduty-prod-api-token` version 1. No token value was printed or written to disk. Secret Accessor was granted to the dedicated runtime on this secret only; `PAGERDUTY_SECRET_ID` selects the named secret.
- Before the first ingestion write, created UAT `Snapshot.PagerDutyProd_before_activation_20261014`, containing the 11,023-row Prod baseline, with a 14-day restore window.
- Authenticated manual delta run (`hours_back=3`, `full_pull=false`) returned HTTP 200, `status=success`, and 17 rows merged in 31.147747 seconds. Prod audit run `6e8cc2d2-a727-4adb-a0a4-c87ff2bd6905` records `SUCCESS`, 17 rows and the same duration.
- Exact post-run checks found 10 inserted keys and 7 changed existing rows, 11,033 unique non-null incident numbers, 17 rows stamped by this run, and zero missing baseline keys. Direct table metadata confirms DAY partitioning on `created_at` and ordered clustering `escalation_policy_name`, `resolved_at`, `created_at` remain intact.
- The first-run Logging API response contained 92 entries, no WARNING/ERROR severity entries, and HTTP request latency of 32.996385193 seconds. This is not a memory-capacity benchmark; retain 512 MiB pending repeated-run/full-catch-up measurements.
- Only recent-data plumbing/MERGE and audit writes had passed at this checkpoint. Older incident updates, enrichment/output parity, full catch-up and multi-day stability remain gates before UAT retirement. The inherited delta filters creation time, not every later status update.
- Subsequent isolated activation is recorded below. Use direct APIs/CLI for this migration; GCP MCP tools are not enabled.

### 9.4.2 Isolated parallel ingestion activation (2026-10-14)

User approved isolated mailbox fan-out, independent Jira destinations/state, protected Prod full refreshes and activation after live validation. Existing UAT ingestion and existing Prod-hosted/UAT-targeted Jira jobs remain enabled and unchanged. No second Gmail poller was deployed.

**HDWL VIP field rollout (2026-10-23):** Added nullable `STRING` column `VIP`
to UAT `GSO.HelpDeskAllNOC` and Prod `BMC.HelpDeskAllNOC`. HDWL configs in both
projects accept this as an optional source header, normalize case/whitespace to
`Yes`/`No`, and map blank or literal `NULL` cells to SQL NULL. Invalid values
fail that attachment rather than entering the table. If an older full export
omits the VIP header, the merge excludes VIP so existing values are preserved;
this maintains compatibility without clearing the column. Current live functions
are UAT `process-bq-hdwl-email-00073-luh` and Prod
`process-bq-hdwl-prod-00007-wox`; both retain their existing Pub/Sub routing,
retry, validation, recovery and IAM settings. The provided
`HelpDesk-data-2026-10-23 06_16_28.csv` parsed successfully: 117 source rows,
103 unique incidents, with 102 `No`, one NULL, and no `Yes` values. That download
was not one of the two HelpDesk attachments processed during deployment; both
contained no VIP header, so current target VIP values remain NULL until a
VIP-bearing export is ingested. The live UAT `GSO.HDWL` and Prod
`Dashboards.HDWL` views now also project the HelpDesk VIP field. No other
downstream views or aggregate grains were changed. The sample values and both
consumer paths are covered by regression tests.

**HDWL compact-header recovery (2026-10-23):** Both consumers rejected valid
HelpDesk exports containing the compact source header `RPO_UMWReason`. The
field map now accepts that spelling, along with `ScheduledStartDate` and
`ScheduledEndDate`, while retaining the deployed VIP handling and merge guards.
The active UAT and Prod bundles were deployed as
`process-bq-hdwl-email-00074-mah` and `process-bq-hdwl-prod-00008-nor`.
After validating sender, subject, both CSV attachments, headers, and usable
rows, 43 failed reports were replayed; all 43 received positive-row `SUCCESS`
audits in both projects. A source-key comparison found all 269 distinct
`Incident_Number` values and all 584 distinct `WorkLog_ID` values in each
environment's target tables, with zero missing keys. The focused UAT regression
suite passed (20 tests). No data gaps were found for this recovery set.

**HDWL compact-response-header recovery (2026-10-26):** Six source reports
failed in both consumers because their HelpDesk CSVs used compact names for the
three GCSC update and three response-time headers. Both field maps now accept
those aliases. UAT `process-bq-hdwl-email-00076-ber` retains Pub/Sub retries;
Prod `process-bq-hdwl-prod-00010-fod` retains its authenticated push and
recovery configuration. The 20-test regression suite passed, all six reports
passed attachment validation and were replayed, and both consumers confirmed
completion. Reconciliation found 2,849 distinct incident keys and 3,947
distinct work-log keys in each target, with none missing. There are zero
unresolved HDWL messages in the latest 48-hour audit/Prod-ledger check.

| Prod function | Input / schedule | Verified result |
|---|---|---|
| `process-bq-hdwl-prod` | Separate Prod push subscription on UAT `gmail-to-bq-hdwl` | Manual merge: 76 rows; repeated natural authenticated Pub/Sub pushes subsequently returned HTTP 200 and produced non-empty `SUCCESS` audits |
| `process-shr-people-prod` | Separate Prod push subscription on UAT `gmail-to-shr-people` | Manual ingestion: 77,282 rows; three cycle files received, not a complete 12-file rebuild |
| `process-srinventory-prod` | Separate Prod push subscription on UAT `gmail-to-srinventory` | Full refresh: 117,562 rows; exact full-row/duplicate-multiplicity comparison with UAT found zero differences |
| `process-training-data-prod` | Separate Prod push subscription on UAT `gmail-to-training-data` | Full refresh: 1,975 rows; exact full-row/duplicate-multiplicity comparison with UAT found zero differences |
| `jira-tickets-prod-validation` | Authenticated Scheduler `*/10 * * * *`, UTC | Manual: 24 rows; Scheduler dispatch: 23 rows; subsequent normal 08:50/09:00 runs: 30/31 rows, all `SUCCESS` |
| `jira-changelogs-prod-validation` | Authenticated Scheduler `*/10 * * * *`, UTC | Manual: 107 rows; Scheduler dispatch: 150 rows; subsequent normal 08:50/09:00 runs: 342/341 rows, all `SUCCESS` |
| `jira-comments-prod-validation` | Authenticated Scheduler `*/10 * * * *`, UTC | Manual: 19 rows; Scheduler dispatch: 13 rows; subsequent normal 08:50/09:00 runs: 18/23 rows, all `SUCCESS` |
| `pagerduty-incidents-sync` | `pagerduty-prod-validation-hourly`, `0 * * * *`, UTC | Scheduler-dispatched three-hour delta: 18 rows, `SUCCESS`, 29.215041 seconds |

- Mailbox labels and outbound notifications remain owned by the original consumers. Prod copies only read attachments. One initial HDWL label comparison overlapped the UAT consumer; a repeat against an already archived message verified unchanged labels and idempotent HTTP 200.
- Four Prod subscriptions use `gmail-prod-invoker`, authenticated push to the corresponding Prod endpoint, seven-day retention and 60-600 second retries. `gmail-prod-runtime` has scoped dataset writer access and can read only the existing UAT Gmail OAuth secret. A natural HDWL push received HTTP 429 at 08:30 while the single instance was occupied; subsequent delivery at 08:31 and later pushes succeeded. Keep this transient in the monitoring record, not as proof of lost data or a reason to permit racing writers.
- [Shared push adapter](../shared/parallel_gmail_validation.py) validates the expected subscription, keeps deduplication scoped by pipeline and Gmail message ID, and acknowledges new delivery only after a non-empty `SUCCESS` audit. The [Gmail deployment helper](../Temp/UAT_to_Prod_Migration/deploy_parallel_gmail.ps1) packages this shared module temporarily and removes its local copy after deployment.
- Gmail business destinations are `BMC` and `Training`; audit, deduplication and SHR cycle state are isolated in `Datapipe`; temporary loads belong in `Staging`. Fourteen-day pre-activation restore snapshots protect `SRInventory`, `TrainingData` and `SHRPeople`.
- Full-refresh Training/SRInventory layouts and Jira target clustering were rechecked after actual writes. Incomplete/timed-out SHR cycles now fail rather than replacing the seeded baseline with partial data. A complete SHR cycle, its history effects and target layout still require live validation.
- Jira copies use `jira-prod-validation-runtime`, `Jira` business tables, `Datapipe` audit logs and UUID-named one-day-expiring `Staging` tables. Invocations use `jira-prod-validation-invoker`. Existing Prod Jira secrets and VPC routing are retained. The first ticket invocation received HTTP 403 during IAM propagation; retry, Scheduler dispatch and normal scheduled runs succeeded without broadening permissions.
- [Jira deployment/schedule helper](../Temp/UAT_to_Prod_Migration/deploy_parallel_jira.ps1) operates only on the three new validation services. HTTP success alone is not validation: check `Datapipe.PipelineRuns`, actual rows and warning/error logs before scheduling.
- Keep inherited memory limits: HDWL 2 GiB; Jira deltas 1 GiB; SHRPeople/SRInventory/PagerDuty 512 MiB; Training 256 MiB. Separate Prod services have their own limits, so doubling environments does not by itself double memory needed inside one service. Monitor memory, retries, Jira/PagerDuty quotas, connector load and cost; do not raise concurrency while shared staging/cycle operations assume one writer.

### 9.4.6 HDWL soft-delete routing and Prod migration status (2026-10-16)

**HDWL empty-export acknowledgement repair (2026-10-21):** UAT
`process-bq-hdwl-email-00071-tiw` and Prod `process-bq-hdwl-prod-00005-jup`
explicitly recognize literal `No data` attachments as `upstream_no_data`.
Only verified all-empty reports receive that report-level terminal skip reason.
The matching Prod push adapter now acknowledges them and writes the existing
processed-message ledger, ending repeated zero-row deliveries. Mixed reports
continue ingesting real data; unknown malformed zero-row payloads are not
blanket-acknowledged. The 28 focused tests passed; existing table mappings,
recovery subscriptions, identities and mailbox ownership were preserved.
Live verification confirmed all six previously looping message IDs now have
informational `upstream_no_data` audits and completed processed-message ledger
entries. Successful HTTP acknowledgements and the duplicate fast path were
observed; historical zero-row audit rows were retained.
See the canonical [incident and repair record](HDWL_Prod_Zero_Row_Investigation_2026-10-21.md).

- Soft-delete uses separate UAT and Prod consumers, not a second CSV merge.
  Gmail subject `pubsub - HD - softdelete` routes through the existing UAT
  `gmail-checker-oauth` to UAT topic `hdwl-softdelete`, which fans out to both
  consumers. Each reads the named `For soft delete` CSV and updates only listed
  `IncidentNumber` keys: UAT `GSO.HelpDeskAllNOC`, Prod `BMC.HelpDeskAllNOC`.
  Audits use `PipelineName=pubsub - HD - softdelete` in UAT `GSO.PipelineRuns`
  and Prod `Datapipe.PipelineRuns`. `RowsMerged` counts newly soft-deleted rows,
  excluding already flagged and missing rows.
- The prior subject `pubsub - HDWL - softdelete` overlapped Gmail's phrase
  search for `pubsub - HDWL`. A control email (`for soft delete …csv`) was
  delivered to both UAT and Prod CSV consumers, which rejected it because it
  had neither HelpDesk nor WorkLog attachments. The subject was renamed and the
  checker deployed at `gmail-checker-oauth-00005-gox`; its HDWL pattern excludes
  `softdelete`. Consumers additionally recognize both subject spellings and
  the known control attachment, log a successful zero-row skip, archive the
  message and acknowledge it. The Prod push adapter accepts zero rows only when
  that explicit skip reason is present.
- The 2026-10-16 audit showed UAT HDWL errors and repeated Prod push errors for
  the same control message ID. The deployed consumers now record a terminal
  `SUCCESS` control-email skip in both projects; Prod also shows ongoing normal
  HDWL ingestion successes. These were routing/acknowledgement errors, not
  missing CSV rows. The control message was replayed only to validate routing,
  not as a data backfill.
- The original soft-delete implementation swept the whole table by
  `Assigned_Group`, instead of processing the email's CSV. Because group
  comparison was case-sensitive, a read-only preview misclassified 603,765
  `Planned Event Mgt` rows (and 116,661 `Soft Switch Management` rows) as
  out-of-scope; no reconciliation was run. The archived `For soft delete`
  attachment contains 18 explicit incident IDs, all `Assigned` to tracked
  `ASOC`. The corrected function validates the CSV and every target ID before
  any mutation, deduplicates related-item rows, and updates only the listed IDs.
  It no longer sweeps or restores tickets based on group. All 18 listed IDs are
  absent from both UAT `GSO.HelpDeskAllNOC` and Prod `BMC.HelpDeskAllNOC`; the
  final UAT run therefore matched 0, flagged 0, verified 0, and recorded
  `SOURCE_INCIDENTS_NOT_FOUND` with `Status=SUCCESS`, `LogLevel=WARNING`, and
  `RowsMerged=0`. No ticket rows were inserted or modified.
- UAT soft-delete's earlier BigQuery SSL EOF happened while submitting an
  idempotent flag update. Its trigger now uses `RETRY_POLICY_RETRY`; the handler
  uses bounded retries for transient BigQuery/TLS failures, parameterized
  incident-ID updates guarded by current flags, and a stable Pub/Sub-event run
  ID. UAT revision `hdwl-softdelete-00015-luf` completed the first controlled
  report replay, sent its summary email, and wrote the verified audit row.
  Earlier revisions exposed and fixed a `datetime` shadowing error and an
  unsupported STRING-to-JSON cast in audit logging. An earlier run sent a report
  email before its audit failed, so the successful replay may have sent a
  duplicate summary.
- **Prod soft-delete deployed and verified with owner approval.** UAT runs
  revision `hdwl-softdelete-00018-xab`; Prod runs HTTP function
  `hdwl-softdelete-prod`, revision `hdwl-softdelete-prod-00002-mon`, in
  `europe-west2` (Python 3.11, 1Gi, 540s). Dedicated Prod subscription
  `projects/pccw-internal-virtual-agent/subscriptions/hdwl-softdelete-prod`
  consumes `projects/pccw-internal-virt-agent-uat/topics/hdwl-softdelete` and
  pushes to `https://hdwl-softdelete-prod-c6zqodieea-nw.a.run.app` using OIDC
  identity `gmail-prod-invoker@pccw-internal-virtual-agent.iam.gserviceaccount.com`.
  Only that identity has `roles/run.invoker` on the service. Runtime identity
  `gmail-prod-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com` reads
  the existing UAT Gmail secret, writes business flags only to `BMC`, and writes
  audit/idempotency state only to `Datapipe`. No second Gmail poller was added;
  the existing HDWL writer, subscriptions and recovery path were not changed.
- The Prod HTTP entry point checks its exact `SOURCE_SUBSCRIPTION` and honors
  `PIPELINE_ENABLED`; rollback is to set `PIPELINE_ENABLED=false` on that service.
  Disabled/failed archive deliveries return non-2xx so Pub/Sub retains them;
  subscription retries use 60-600s backoff, a 600s acknowledgement deadline and
  seven-day retention. Prod's function-owned `env.yaml` records its config;
  deploy with `--trigger-http --entry-point=main --no-allow-unauthenticated`
  and that env file, then preserve/recheck the authenticated invoker binding.
- Both consumers now remove `pubsub` and `UNREAD` and add `ArchivedReports`
  only after verified processing and a successful audit, including completed
  missing-ID warnings. A failed archive preserves the success audit and retries
  only archive cleanup on redelivery. UAT's CloudEvent entry point raises on
  retryable failures (returning a status tuple alone would be acknowledged by
  Functions Framework). Previously published messages remain independently
  deliverable to both consumers even after the shared Gmail label is removed.
- Live end-to-end verification at 07:06 UTC replayed the one remaining queued
  email `1a1434db0bbbaf98` (`For soft delete 10-16-2026 6-1-59.csv`, legacy
  subject). Read-only preflight found its 18 unique IDs absent in both targets.
  Both consumers recorded `RunID=softdelete_1a1434db0bbbaf98`, `Status=SUCCESS`,
  `LogLevel=WARNING`, `ErrorCode=SOURCE_INCIDENTS_NOT_FOUND`, `RowsMerged=0`;
  no ticket rows were inserted or modified. Both sent summary emails; Prod logs
  confirm archiving. Gmail now shows `ArchivedReports`, no `pubsub` or `UNREAD`,
  and zero remaining soft-delete messages under `pubsub`. A natural new-subject
  email has not yet been observed after this deployment; the controlled replay
  verified actual authenticated topic fan-out and both consumer paths.

- Soft-delete success and error audits now populate `DurationSeconds` as
  `FLOAT64` elapsed processing seconds using a monotonic clock. Measurement
  starts when reconciliation begins and stops just before its final audit
  write; final Gmail archive cleanup is excluded. Completed duplicate deliveries
  preserve the original audit duration. Historical NULL values were not
  estimated or backfilled. Both audit MERGEs passed BigQuery dry runs against
  their live tables; all 37 focused tests pass. UAT and Prod duration-enabled
  revisions are the current revisions listed above; the next fresh report will
  exercise the new field in a real run.

**Ticket-view soft-delete policy (deployed 2026-10-16)**

- All 25 direct logical views reading the ticket table now require
  `Soft_Delete_Flag IS NOT TRUE`: 12 UAT views / 14 ticket-read branches, and
  13 Prod views / 15 branches. Live metadata confirms zero unfiltered direct
  readers. This keeps existing `NULL` and `FALSE` flags visible.
- Coverage includes `AgentDataset.JIRA_RemedyTicket`; UAT `GSO` / Prod
  `Dashboards` views `HDWL`, `HDWL_Shift`, `HD_CarrierVendor`, `JIRA_HD`,
  `RemedyJira`, `SRInventory_HD`; UAT `Looker.HD_CarrierVendor`; both projects'
  `Restricted.BQAgent_CustomerData`, `Restricted.TicketFinance`,
  `wanda_ds.RemedyJira`, `wanda_ds.TicketMaster`; and Prod
  `wanda_ds.RemedyJira_uat_migration`, `wanda_ds.TicketMaster_uat_migration`.
  Existing cross-project source mappings were preserved.
- Inventory views filter the ticket input before their LEFT JOIN, preserving
  inventory-only rows. Full-outer Jira combinations filter the joined ticket
  flag afterward, preventing deleted HelpDesk incidents from returning as
  Jira-only rows while keeping genuinely independent Jira rows. All three
  creation/closure/work-log branches in `HDWL_Shift` are filtered; existing
  Remedy/Jira OR conditions remain explicitly grouped.
- All 25 definitions passed BigQuery dry runs with unchanged effective output
  schemas; updates changed only view query text and preserved live metadata
  and comments. The 24 downstream logical views (11 UAT, 13 Prod) inherit the
  filters and compile against the updated parents. The UAT
  `wanda_ds.RemedyJiraWithDeviceNames` wildcard required an explicit exclusion
  of the three newly inherited `Soft_Delete_*` fields to preserve its saved
  212-column contract; that targeted fix was deployed and verified too.
- Seven in-warehouse fixture checks passed for `NULL`/`FALSE` flags, deleted
  full-join rows, independent Jira rows, inventory row preservation, deleted
  inventory links and active/deleted work logs. No ticket data was modified.
  Scheduled refresh jobs, stored enrichment/history tables and ad hoc/backfill
  SQL were not changed as part of this view-only policy.

**Remaining gates / not duplicated yet**

- Natural push delivery has been observed for HDWL, not yet for the other three mailbox topics. Their authenticated manual attachment tests passed; wait for fresh source events and inspect backlog/delivery errors.
- The initial three Jira copies are recent deltas. Independent nightly/weekly/continuation copies were subsequently enabled as described in section 9.4.4; full catch-up is still running. The separately modified original nightly implementation was not redeployed.
- `BMC.UserList` dual-writes Prod/UAT from the UAT `process-bq-bmc-user-list-email` function. Revision `process-bq-bmc-user-list-email-00007-jog` also writes each run (RUNNING and terminal status) to both UAT `GSO.PipelineRuns` and Prod `Datapipe.PipelineRuns` using the same `RunID`. UAT `RowsMerged` remains the combined count; the Prod audit reports only Prod's target count. The UAT function service account has Prod `roles/bigquery.dataEditor`; the Prod audit MERGE passed a BigQuery dry run. On 2026-10-20 the checker found four queued BMC User List emails but could not publish: topic `gmail-to-bmc-user-list` returned `403 IAM_PERMISSION_DENIED` for `pubsub.topics.publish`; no function invocations or audits followed. Added only `roles/pubsub.publisher` for the existing checker identity `jira-bigquery@pccw-internal-virt-agent-uat.iam.gserviceaccount.com` on that topic. The checker then published all four messages and all four runs completed `SUCCESS` with matching UAT/Prod RunIDs and terminal audit rows. UAT row counts were 888/889/890 (combined); Prod counts were 444/444/445 per target. This deployment did not modify topic IAM; the reason the publisher grant was absent is undetermined. Prior audit history was not backfilled. The UAT HDWL recovery republisher still fans out to both environments. The additional recovery job in section 9.4.5 reads only Prod failures and publishes only to a Prod topic.
- A read-only Prod daily report is enabled without outbound notifications (section 9.4.5). GAS remains blocked by live project HTTP 403, missing script/trigger-owner inventory and unverified properties. The Training sheet feeder, HubSpot and additional verification connectors still need confirmed ownership/mappings.
- External Helix actions, AI/translation queries and recovery mirrors were deliberately excluded. No dashboard/view connection cutover or UAT shutdown was performed.
- Multi-day stability, full catch-up and dashboard query-performance measurements remain required. Clustering presence is not proof of faster dashboards.

### 9.4.3 Datapipe monitor sources and checkpoint baseline (2026-10-14)

The monitor's four BigQuery sources map to:

| Monitor source | Prod object | Migration behavior |
|---|---|---|
| PipelineRuns | `pccw-internal-virtual-agent.Datapipe.PipelineRuns` | Reuse the existing live Prod run log; do not copy UAT history over it |
| DataProgress | `pccw-internal-virtual-agent.Datapipe.DataProgress` | Same view schema, reading only the three Prod progress tables |
| DataStudioUsage | `pccw-internal-virtual-agent.Admin.DataStudioUsage` | Same schema, reading Prod EU job metadata and Prod report-name lookup |
| view_usage_monitor | `pccw-internal-virtual-agent.Admin.view_usage_monitor` | Same schema, monitoring only Prod EU views and successful query jobs |

- User explicitly approved populated progress baselines rather than empty control tables. Empty progress can cause a future nightly worker to start historical backfill; simply creating these tables does not trigger any worker.
- The [migration helper](../Temp/UAT_to_Prod_Migration/migrate_monitor_sources.ps1) requires recorded exact Jira source-seed verification. It seeds progress using BigQuery time travel at the same `2026-10-14T06:53:21.279Z` snapshot as the business-table baseline, not newer UAT progress that could skip changes missing in Prod.
- Verified copies: `JiraComments_progress` 6,891 rows; `JiraChangelog_progress` 6,776 rows; `JiraTickets_progress` 6,772 rows. All source baseline rows were `complete`; each full-row/duplicate-multiplicity comparison returned zero differences. Ordered clustering is `Project, WindowStart, WindowEnd`; all source fields, including 429 counters, are preserved.
- These rows represent **inherited coverage of the seeded data**, not evidence of newly executed Prod nightly runs. Window-end watermarks differ by source/project. Existing progress does not establish full catch-up after the seed; replay uncovered windows and migrate separate continuation/key/repair state before enabling nightly workers.
- `Admin.DataStudioReportLookup` is independently seeded with 64 report-name mappings, exactly verified and clustered by `looker_studio_report_id`. Its Apps Script updater has not been migrated: new/renamed report names require a later verified refresh. Usage itself is live job metadata, not a copied UAT usage history.
- Canonical SQL is [DataProgress](../pccw-internal-virtual-agent/BigQuery/Datapipe/views/DataProgress.sql), [DataStudioUsage](../pccw-internal-virtual-agent/BigQuery/Admin/views/DataStudioUsage.sql) and [view_usage_monitor](../pccw-internal-virtual-agent/BigQuery/Admin/views/view_usage_monitor.sql). No UAT object, active worker, scheduler or existing Prod log is replaced.
- All three deployed views passed schema compatibility and actual queries: `DataProgress` 20,439 rows; `DataStudioUsage` 67,466 rows; `view_usage_monitor` 743 rows at verification. Nullable-mode omission in the API is normalized when comparing schemas; field names, order and types match the UAT monitor sources.
- Usage views preserve the existing job-history scope. Each unrestricted validation scan estimated approximately 6.5 GB and ran under a 10 GB billing cap. Use a suitable date range in the report and measure actual query pruning/cost; the views are not precomputed dashboards.
- Execution refuses populated targets rather than overwriting them. If only view deployment needs resuming after verified dependency copies, `-Execute -ViewsOnly` reuses those dependencies and identical owned views without replacing them. Keep the result/evidence files outside the repository.
- Reconnect the four Looker Studio data sources to these Prod objects and use Prod as the billing/query project. The actual report connection is not changed by creating BigQuery objects. Refresh fields and check report rendering after reconnecting.
- The report's BigQuery credential identity needs access to the selected tables/views, BigQuery Job User on its billing project and project job-metadata visibility (for example, BigQuery Resource Viewer on Prod) for the two usage views. Do not grant broad roles to an unknown report identity. Ordinary table viewer access alone does not expose all project job metadata.

### 9.4.4 Independent Jira nightly, weekly and continuation rollout (2026-10-14)

Three new services are enabled: `jira-tickets-nightly-prod-validation`,
`jira-comments-nightly-prod-validation` and `jira-changelogs-nightly-prod-validation`.
They were generated from generation-pinned deployed archives, not the unrelated
local recovery edits in the existing ticket nightly folder. Originals and their
schedules remain unchanged.

- Business writes go to `Jira`; progress, batch manifests, ticket state/keys/repairs
  and audits go to `Datapipe`; run-specific temporary loads go to `Staging` with
  seven-day expiry. The strict [destination map](../shared/isolated_jira_destinations.py)
  rejects unknown table names rather than defaulting them into a dataset.
  Common logging, batch-checkpoint and comments/changelog table helpers live in
  `shared/`; deployment packages their verified aliases temporarily and removes
  the generated copies afterward. Ticket-specific runtime code stays with its
  function. Moving these identical helpers does not alter deployed behavior.
- Existing runtime/invoker identities and Prod Jira secrets/VPC are reused. All
  services retain 2 GiB memory, one instance and concurrency one. Jira request
  spacing is one second for these new copies. Ticket nightly budget is 1,200
  seconds; weekly maintenance is 480 seconds; comments/changelog use their
  deployed 1,200-second default.
- `PIPELINE_ENABLED` defaults false. Soft-delete reconciliation remains explicitly
  disabled for the parallel batch. Weekly maintenance can populate independent
  snapshots and repair missing/drifted tickets without soft-deleting Prod data.
- [Checkpoint migration](../Temp/UAT_to_Prod_Migration/migrate_nightly_state.ps1)
  uses the same verified business seed timestamp, `2026-10-14T06:53:21.279Z`.
  Source ticket maintenance was in flight at that timestamp. Only entirely
  completed runs and completed batch windows were copied; incomplete UAT cursors,
  keys and repairs were excluded together, never resumed against missing staging.
  Fresh Prod work replays uncovered periods and performs its own maintenance scan.

| Checkpoint baseline | Rows copied | Exact full-row/duplicate differences |
|---|---:|---:|
| `Datapipe.JiraTickets_nightly_state` | 50 | 0 |
| `Datapipe.JiraTickets_nightly_keys` | 450,488 | 0 |
| `Datapipe.JiraTickets_nightly_repairs` | 15,010 | 0 |
| `Datapipe.JiraComments_progress_batches` | 151 | 0 |
| `Datapipe.JiraChangelog_progress_batches` | 156 | 0 |

Bounded single-project ticket nightly and weekly tests returned `SUCCESS` with
zero rows (no changes in those tested windows). Comments/changelog initially
merged 1/4 rows, saved `PAUSED` checkpoints, and actual resume calls then returned
`SUCCESS`. All-project invocations subsequently merged **98 tickets, 168 comments
and 544 changelog rows** and returned `PAUSED` with persisted checkpoints at their
time budgets. This is verified catch-up progress, **not** completed full catch-up.
Comments' resume guard retains the deployed dependency on the latest successful
Prod changelog nightly audit.

Eight authenticated schedules are enabled, offset from the originals:

| Prod job | Cron | Time zone | Payload |
|---|---|---|---|
| `jira-tickets-nightly-prod-validation` | `50 15 * * *` | UTC | `mode=delta, resume_only=false` |
| `jira-tickets-nightly-prod-resume` | `12,42 * * * *` | UTC | `mode=delta, resume_only=true` |
| `jira-tickets-weekly-prod-validation` | `5 2 * * 6` | Asia/Hong_Kong | `mode=maintenance, resume_only=false` |
| `jira-tickets-weekly-prod-resume` | `2,32 * * * *` | UTC | `mode=maintenance, resume_only=true` |
| `jira-comments-nightly-prod-validation` | `35 15 * * *` | UTC | `resume_only=false` |
| `jira-comments-nightly-prod-resume` | `20,50 * * * *` | UTC | `resume_only=true` |
| `jira-changelogs-nightly-prod-validation` | `20 15 * * *` | UTC | `resume_only=false` |
| `jira-changelogs-nightly-prod-resume` | `5,35 * * * *` | UTC | `resume_only=true` |

Use [source preparation](../Temp/UAT_to_Prod_Migration/prepare_nightly_sources.py),
[deployment](../Temp/UAT_to_Prod_Migration/deploy_parallel_nightly.ps1),
[manual/audit validation](../Temp/UAT_to_Prod_Migration/validate_parallel_nightly.ps1)
and [schedule configuration](../Temp/UAT_to_Prod_Migration/configure_parallel_nightly_schedules.ps1).
Schedules are created paused before enabling; enabling requires real all-project
audit evidence and all-project function settings. Any activation error pauses the
eight copies. Disabling these new jobs/functions is the rollback; do not delete
state or touch the original UAT jobs.

### 9.4.5 Prod-only recovery and read-only reporting (2026-10-14)

- `pipeline-daily-report-prod-validation` reads only Prod `Datapipe.PipelineRuns`.
  Its runtime has BigQuery Job User and `READER` on `Datapipe`. Initial parallel
  validation deliberately omitted Gmail delivery. On **2026-10-15**, the owner
  approved automatic Prod delivery to the same recipient as UAT, distinguished
  by a **`[PROD]` subject prefix**. The daily schedule remains **08:15 HKT**;
  UAT reporting is unchanged.
- Delivery requires explicit `NOTIFICATIONS_ENABLED=true`; it defaults off.
  `PIPELINE_ENABLED` must also be true. The report runtime
  `pipeline-report-prod-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com`
  now has Secret Accessor only on the existing UAT `gmail-oauth-token` secret,
  configured through `SECRET_PROJECT_ID`. No secret was copied into Prod or
  stored in the repository. This preserves the shared Gmail/UAT-secret dependency
  that must be resolved before UAT retirement.
- [Report implementation](../pccw-internal-virtual-agent/CloudFunctions/pipeline_report/main.py)
  rejects missing Gmail message IDs and returns/logs delivery failures as HTTP
  500, rather than reporting successful delivery. Deploy with
  [deployment helper](../Temp/UAT_to_Prod_Migration/deploy_parallel_ops.ps1)
  `-Consumer Report -EnablePipeline -EnableReportDelivery`; omitting the delivery
  switch explicitly disables notifications. Reports cover the Prod audit ledger,
  not every GAS job or DTS configuration automatically.
- A real authenticated Scheduler invocation at **17:59 HKT on 2026-10-15**
  returned HTTP 200. Gmail returned message ID `1a13f011515cea9b`, and completion
  logged **one anomaly**. This proves sender acceptance, not independently
  observed Slack receipt. The enabled 08:15 HKT schedule was read-back verified.
- `hdwl-daily-rerun-prod-validation` reads only Prod previous-HKT-day HDWL failures
  and publishes only to `gmail-hdwl-prod-recovery` in Prod. Dedicated authenticated
  subscription `process-bq-hdwl-prod-recovery` targets the existing Prod HDWL
  consumer; it cannot trigger the UAT consumer. Daily schedule is **08:05 HKT**.
- The shared push adapter accepts the normal source subscription plus only the
  explicitly configured recovery subscription. Deduplication still uses the
  Prod pipeline/message ledger. Recovery IDs and reason are preserved in the
  Prod consumer audit. Shared UAT recovery events remain accepted under a separate
  Prod run identity; their UAT cursor/run ID is never adopted.
- Dry-run discovery and actual recovery execution passed with **zero eligible
  failures**. An already completed email verified the duplicate-delivery route
  without repeating its data processing, and a real event was published to the
  Prod-only topic. This does **not** establish a successful new-data failure replay;
  observe the first genuine recovery and its terminal consumer audit.
- Selector guards skip messages with later successful Prod ingestion. Pending
  asynchronous recoveries remain explicit per-message `PENDING` with summary
  `WARNING`, not proof of recovered data. Retain the deployed summary convention
  (`SUCCESS` plus warning for pending publication); alerts must inspect pending
  counts and actual consumer outcomes.
- [Preparation](../Temp/UAT_to_Prod_Migration/prepare_ops_sources.py) uses pinned
  deployed archives. [Deployment](../Temp/UAT_to_Prod_Migration/deploy_parallel_ops.ps1),
  [validation](../Temp/UAT_to_Prod_Migration/validate_parallel_ops.ps1) and
  [schedules](../Temp/UAT_to_Prod_Migration/configure_parallel_ops_schedules.ps1)
  operate only on the new Prod resources. Recovery starts dry-run-only and is
  opened only after discovery/routing validation.

Remaining blockers are Apps Script trigger ownership/first successful dual-write
runs, the remaining manual Drive HDWL destination update, a complete SHR cycle, natural deliveries on
the other mailbox topics, full Jira catch-up, multi-day stability and the separate
dashboard connection/performance cutover. The intentional external-action,
AI/translation and backup/mirror exclusions still apply.

### 9.5 Step 3 — Views & dashboards (migrate the definition, then the connection)

For each dashboard/view:

1. [ ] Create the Prod-side view first, backed by Prod tables (DDL compile-check).
2. [ ] Verify the view returns the same result set as the old one (spot-check dimensions).
   - Pass the §9.2.1 performance gate using representative dashboard queries against the Prod backing tables before changing the report connection.
3. [ ] Update the report connection (Dashboards/Looker) to the new Prod dataset — or update the view definition only if the report references a fixed dataset.
4. [ ] Verify the dashboard renders with fresh data and re-validates.

- If a dashboard uses a hard-coded `project.dataset.view`, normally update the report config rather than rewriting an in-use view. The owner-approved paid-output continuity change in section 9.5.1 is a scoped exception: change only the paid table references, verify unchanged output schemas, and leave dashboard connections unchanged.

### 9.5.1 View/source migration checkpoint (2026-10-15)

- Of 74 scoped UAT views, **64 Prod definitions were created and current logical output schemas verified**, six existing Prod definitions retained, and four remain blocked. Backup/test views and other Looker views are excluded; only `Looker.vw_centre_operations_circuit_availability` was approved for duplication.
- Existing conflicting Prod definitions were not overwritten. Their UAT-derived copies use `_uat_migration`, with dependent references redirected to those copies. The retained definitions are `Admin.DataStudioUsage`, `Admin.view_usage_monitor`, `BMC.UserListCleaned`, `Datapipe.DataProgress`, `wanda_ds.dlp_redaction_allowlist` and `wanda_ds.dlp_redaction_allowlist_manager_view`. Retention alone is not full output-parity certification; the canonical usage monitor additionally passed Prod-only SQL, schema and dry-run checks.
- Views use explicit projections of the current UAT query output, not potentially stale stored view schemas. A concurrent `GSO.TrainingData_cleaned` change stopped deployment; the owner approved its latest definition, which is now persisted in Prod and the canonical UAT SQL.
- At this checkpoint, `GSO.graph_landscape_detailed` needed metadata/project adaptation; it was subsequently recreated in Prod `Admin` on 2026-10-22 (see below). Billing was subsequently verified and created in Prod `Dashboards` on 2026-10-27; its UAT literal is an intentional display-label mapping, not a UAT dependency. Two recorded blockers remain: `wanda_ds.RemedyJiraWorkLogView` contains unresolved legacy/UAT logic; `GSO.CSMKPI` already fails in UAT because `Transition_Timestamp` is absent from its status STRUCT. Do not silently alter their semantics or claim all views migrated.
- Additional prerequisites copied: 11 physical baselines (`Dashboards.2025SurveyResponse_clustered`, `BMC.HDWL_AIInfused`, `Jira.MSS_AIInfused`, `Admin.Staff`, `Verification.VerificationDisputeList`, three `GSOEDPLink` business tables, `Dashboards.RemedyOutstandingSnapshot`, `wanda_ds.CCAI_Dialogflow_Transcript_Translated`, `wanda_ds.device_name_reference`) and four external Sheet definitions (`Verification.VerificationTeamNames`, `QMS.ICAIR`, `QMS.RawCorrectiveAction`, `QMS.RawIncident`). Copying a Sheet definition does not establish Drive-authorized runtime access.
- The three business tables are `GSOEDPLink.CostItemSnapSnapshot`, `GSOEDPLink.EDP-SR` and `GSOEDPLink.all_cost_items_report`. `CostItem` and `SR` now use verified EU Prod replicas instead of querying the remote warehouse directly. Their independent recurring refresh remains outstanding.
- Translation state was separately copied with exact row/duplicate-multiplicity comparisons: `wanda_ds.translation_cache` (2,340 rows; clustering `text_hash`) and `wanda_ds.translation_failed_queue` (one row; clustering `conversation_id, fail_stage`). Both clustering layouts were rechecked after cutover.
- Actual bounded Prod reads passed with rows for circuit availability, `HDWL`, `HubspotSCNFeedbackAgg`, `Restricted.BQAgent_CustomerData`, `TrainingData_cleaned`, `CostItem` and `SR`. These are runtime-access checks, not complete aligned-snapshot output comparisons or dashboard performance certification.
- `Dashboards.Verification_PR_Requester_Performance` passed migration/schema checks, but its subsequent actual CLI read failed with `Permission denied while getting Drive credentials`. Its Sheet-backed dependency needs Drive-capable runtime credentials, like the GSO agent's `QMS.ICAIR` source. Do not count this as a successful runtime read or assume more BigQuery IAM fixes the OAuth scope restriction.
- **Twelve existing UAT views now read Prod paid outputs**, preserving their before/after logical schemas: `AgentDataset.JIRA_RemedyTicket`; `GSO.HDWL`, `GSO.JIRA_HD`, `GSO.MSS`, `GSO.RemedyJira`; `Restricted.BQAgent_CustomerData`; and `wanda_ds.CCAI_Dialogflow_Dedup_Transcript`, `wanda_ds.RemedyJira`, `wanda_ds.RemedyJiraHS_View`, `wanda_ds.RemedyJiraWithDeviceNames`, `wanda_ds.RemedyJira_AI`, `wanda_ds.TicketMaster`. Named authorized-view entries were added to the relevant Prod `BMC`, `Jira` and `wanda_ds` dataset ACLs without replacing existing access entries. All twelve definitions persisted and actual one-row reads passed.
- The `RemedyJiraHS_View` read exceeded the local two-minute wait but completed successfully in BigQuery. Its existing job was recovered without resubmission; resumable validation now records pending read jobs. This does not waive the dashboard latency gate.
- Dashboard/report connections remain unchanged. Indirect consumers follow the updated views; direct consumers of the old UAT physical AI/translation tables are not automatically redirected. Those tables remain frozen rollback assets, not fresh outputs.
- [View planning](../Temp/UAT_to_Prod_Migration/plan_view_migration.cjs), [guarded deployment](../Temp/UAT_to_Prod_Migration/deploy_prod_views.cjs) and [paid-output continuity](../Temp/UAT_to_Prod_Migration/repoint_uat_paid_views.cjs) retain scoped ownership/concurrency checks. Generated inventories, before/after definitions and validation journals stay outside the repository.

### Billing view migrated to Dashboards (2026-10-27)

- Owner approved `pccw-internal-virtual-agent.Dashboards.billing`, using the existing plural `Dashboards` dataset rather than `wanda_ds`. Prepared canonical [billing.sql](../pccw-internal-virtual-agent/BigQuery/Dashboards/views/billing.sql) from the repository's UAT view definition.
- Preserve the shared source `console-core-billing-data.console_core_gcp_billing_shared.v_virtual_agent_billing` and both UAT/Prod project label mappings. The UAT project literal is a display-label condition, not an ingestion dependency; it must not be blindly rewritten. No billing export or source-data copy is required.
- **Created and runtime-verified:** after the owner changed sandbox permissions, CLI authentication and direct REST API access succeeded. Fresh live UAT SQL matched canonical SQL after newline normalization. The source, shared billing view and target dataset are EU; the target was absent and was created without overwriting existing objects.
- Persisted SQL and all **13 ordered field names/types/modes** match UAT. A bounded actual read covering the last seven days succeeded and returned a row indicator without exposing billing values. Source UAT etag remained unchanged. The initial 1 GB query cap was insufficient (BigQuery required about 3.47 GB); validation completed with a 5 GB per-job cap and `datacloud=vscode` labels.
- No IAM policy or dashboard connection was changed. Consumers still require access to the shared billing source unless a separately approved authorized-view setup is configured. No ingestion or refresh schedule is needed for this logical view; clustering applies to the underlying source, not the view.
- Guarded [deployment helper](../Temp/UAT_to_Prod_Migration/migrate_billing_view.cjs) verifies live source SQL and schemas before creating an absent target, refuses differing existing targets, and performs runtime verification. Metadata and job evidence remain outside the repository.

### Prod dependency graph adaptation (2026-10-22)

- Created **`pccw-internal-virtual-agent.Admin.graph_landscape_detailed`** as a logical view, preserving the original name and ten output column names/types. UAT was unchanged, no existing Prod object was overwritten, and no dashboard connections were switched.
- Unlike the UAT `GSO`-only graph, it reads project-wide **EU** `INFORMATION_SCHEMA.TABLES` and `VIEWS`, so new EU datasets/objects are discovered at query time without maintaining a dataset list. Non-EU datasets and other projects are outside this graph's scope. Query it in EU; callers need project-wide metadata visibility, not merely access to the Admin view.
- Internal dependency keys use full `project.dataset.object` identifiers, preventing collisions between identically named tables in different datasets. Output node names use `dataset.object` for compatibility with the original node format. Fully qualified and dataset-qualified references, separately backticked components and unquoted qualified `FROM`/`JOIN` references are recognized. One-part names, dynamic SQL, routine lineage, comments/string-literal disambiguation and SQL parsing edge cases are not comprehensively resolved: this is SQL-inferred lineage, not an authoritative parser/catalog lineage service.
- Traces view dependencies to terminal `BASE TABLE`, `EXTERNAL`, `MATERIALIZED VIEW`, `CLONE` and `SNAPSHOT` objects. External Sheets appear as terminal nodes without reading their contents, so Drive OAuth is not needed to generate this metadata graph. Materialized-view internals and underlying external resources are not expanded. Objects whose names start with `graph_` are excluded.
- Preserved the original eight-hop limit, shortest-depth output and dependency-path counts; added visited-node cycle guards. Because inference is heuristic, output confidence is now **80 / MEDIUM**, rather than the original unconditional **100 / HIGH**. Consumers should not treat the numeric score as measured statistical confidence. `source_type` reflects the actual terminal object type instead of always saying `BASE TABLE`.
- Synthetic BigQuery tests passed for cross-dataset same-name collisions, direct/transitive paths, duplicate-path counts, quoted/segmented/unquoted qualified identifiers, external terminals, cycles, graph exclusions and excluding another project's references. The fixture returned eight expected edges. Persisted SQL and the ten-column schema were read-back verified.
- A complete actual graph aggregate query succeeded: **248 edges**, **223 cross-dataset edges**, **four external-source edges**, and **zero invalid depths**. These are verification-time counts, not fixed expected totals. Schema verification for the earlier 64-view batch remains historical; this independently adapted view resolves one of its four recorded blockers.
- Canonical [view SQL](../pccw-internal-virtual-agent/BigQuery/Admin/views/graph_landscape_detailed.sql); guarded [deployment and SQL fixture tests](../Temp/UAT_to_Prod_Migration/migrate_prod_lineage.cjs). The helper creates only an absent target or verifies an exactly matching existing view. Validation evidence remains outside the repository. Logical metadata views do not support clustering.
- **Looker Studio reconnection remains unresolved (2026-10-22):** the connection-change dialog reported missing `high_signal_key_count`, `medium_signal_key_count`, `low_signal_key_count`, `shared_key_columns`, `shared_key_columns_text`, `shared_key_types`, `shared_key_types_text`, `shared_key_count` and `sample_join_sql`, while showing `edge_method`, `lineage_depth` and `evidence` as new. A fresh live comparison confirmed both UAT and Prod currently expose the same ten field names/types; none of the reported missing fields exists in the live UAT view either. The report may retain an older schema or refer to a different original source; that cause is not yet verified. Do not apply the reconnection until the original report connection/definition is identified and affected charts are validated. No placeholder fields were added, and BigQuery schema parity does not establish report compatibility.

### CustomerSuccessTracking Sheet migration (2026-10-22)

- Created EU dataset `pccw-internal-virtual-agent.Gsheet` and external table `Gsheet.CustomerSuccessTracking` from `pccw-internal-virt-agent-uat.GSO.CustomerSuccessTracking`. UAT was left unchanged; no dashboard, agent or dependent-view references were switched.
- Preserved all 21 nullable fields, their types, the original Google Sheets URI, worksheet range `New Onboarding`, one skipped header row, `autodetect=false` and `ignoreUnknownValues=false`. The Prod table reads the same live Sheet; no physical data snapshot, separate Sheet copy or refresh schedule was created.
- Read-back verified the Prod definition and EU location against the source, with no table/dataset expiry. Added `datacloud=vscode` attribution. No UAT dataset ACLs or Sheet sharing permissions were cloned; readers require appropriate Prod BigQuery access plus Drive-authorized credentials and access to the underlying Sheet.
- Clustering exception: Google Sheets external tables do not support BigQuery clustering. Keep this as a live external table; a clustered native materialization would require a separately approved ingestion/refresh design.
- Both UAT and Prod actual read probes failed with `Permission denied while getting Drive credentials` under the current CLI credentials. Definition migration is complete, but end-to-end data reads are **not verified**. This does not establish a target-only permission failure or empty Sheet; external-table metadata row counts are not data validation. Use a Drive-authorized consumer that already has Sheet access to complete runtime validation. No OAuth scope workaround was attempted.
- Canonical definition: [CustomerSuccessTracking.sql](../pccw-internal-virtual-agent/BigQuery/Gsheet/CustomerSuccessTracking.sql). The guarded [migration helper](../Temp/UAT_to_Prod_Migration/migrate_customer_success_tracking.cjs) creates only absent targets, refuses incompatible existing definitions and checks source concurrency. Metadata and validation evidence remain outside the repository.

### ICAIR Sheet copy into Gsheet (2026-10-22)

- Created `pccw-internal-virtual-agent.Gsheet.ICAIR` in EU from live `pccw-internal-virt-agent-uat.GSO.ICAIR`. Preserved all **31 nullable STRING fields**, their order, the original Sheet URI, worksheet range `Incident`, one skipped header row, `autodetect=false` and `ignoreUnknownValues=false`. Persisted schema and external configuration were read-back verified exactly; no expiration or physical data snapshot was introduced.
- An identical external definition already exists at Prod `QMS.ICAIR` from the earlier migration. It remains unchanged for existing agents/views; no callers were repointed, no original was deleted, and its etag plus the UAT source etag were verified unchanged. Both Prod definitions read the same live Sheet, not separately maintained copies of its data.
- Both source and target actual read probes remain blocked by `Permission denied while getting Drive credentials` under the CLI credentials. Runtime data access is not yet verified. Consumers need Prod dataset access, Drive-authorized credentials and Sheet access; no permissions or credentials were cloned. Google Sheets external tables do not support clustering.
- Canonical [ICAIR.sql](../pccw-internal-virtual-agent/BigQuery/Gsheet/ICAIR.sql). The existing [Sheet migration helper](../Temp/UAT_to_Prod_Migration/migrate_customer_success_tracking.cjs) now accepts an optional `ICAIR` argument after the evidence directory; without it, the original `CustomerSuccessTracking` behavior is preserved. Generated metadata and validation evidence stay outside the repository.

### 9.5.2 Four Prod data agents (2026-10-15)

| Agent | Prod ID in location `eu` | Verified state |
|---|---|---|
| Wanda Ops Analyst | `wanda-ops-analyst-eu` | Created; authored context read-back and datasource reads passed |
| Cable Agent | `cable-agent-eu` | Created; authored context read-back and datasource reads passed |
| GSO Center Operations Data Analyst (EU) | `gso-center-operations-data-analyst-eu` | Created; authored context read-back passed; `QMS.ICAIR` actual read blocked by Drive credentials |
| Customer Data | `customer-data-eu` | Created; authored context read-back and datasource reads passed |

- [Agent migration](../Temp/UAT_to_Prod_Migration/migrate_prod_agents.cjs) uses `https://geminidataanalytics.eu.rep.googleapis.com/v1beta` and the tenant-matching `X-Goog-User-Project` header. Both staging and published contexts, instructions, glossary, schema descriptions and examples were copied; output-only API fields were excluded. Normal and separately backticked SQL identifiers were mapped to Prod.
- Required partition filters are included in datasource probes. The verified training alias `Item_Title` became `TrainingTitle`; removed cached fields retain their descriptions as explicitly non-selectable legacy notes, rather than invented replacements. Column compatibility is case-insensitive; a live check found no case-only differences requiring changes to the deployed contexts.
- Direct resource sharing was copied and read-back verified for all four, preserving the destination creator owner. [Sharing migration](../Temp/UAT_to_Prod_Migration/copy_agent_sharing.cjs) does not clone whole-project IAM or grant underlying dataset access to application principals.
- The remaining Drive failure is an OAuth-client restriction: explicitly requesting Drive scope returned `restricted_client: Unregistered scope(s) in the request: https://www.googleapis.com/auth/drive`. Another CLI login or additional BigQuery IAM does not resolve this. Use a properly registered Drive-capable credential/client, or seek separate approval for materializing the source; no scope workaround was applied.
- Application-principal datasource access, conversational API smoke tests, and client tenant/agent-ID cutover remain separate gates. Existing callers still use the original agents; original agents were not deleted.

### 9.6 Step 4 — Scheduled queries & Cloud Scheduler

- Do **not** delete existing scheduled queries by default. The owner explicitly approved moving the four AI/translation configurations into Prod and deleting only their verified, paused UAT originals (section 9.6.3). This exception does not authorize deleting other schedules.
- Add the Prod-side job disabled/paused first; validate inputs, outputs, IAM and schedule before activation. Preserve the disabled status of inactive UAT jobs rather than automatically enabling them.
- Parallel runs require separate output and runtime destinations with no duplicate external effects.
- Once outputs match and there are no errors, disable the old UAT job (with ops sign-off); keep its configuration for rollback. For the approved paid-job exception, archive original definitions outside the repository before deletion and verify replacement execution, restored full SQL and intended enabled/paused state.

### 9.6.1 Connector and schedule discovery checkpoint (2026-10-14)

- EU DTS discovery found 31 UAT transfer configurations: 24 CenterOps hourly dashboard snapshot queries, five other scheduled queries, and two cross-region copy transfers. No Prod EU transfer configurations were returned. This is EU discovery, not proof that every region has been inventoried.
- The other scheduled queries are MSS AIInfused (disabled), HDWL AIInfused, SR Count Record, SHRPeople Monthly Snapshot Counts and CCAI Dialogflow Translation. Classify the actual output, not just the dataset/name: dashboard/operational snapshots belong in Prod; genuine backup/mirror copies remain in UAT reading Prod.
- Scheduler discovery in `europe-west2` found 16 UAT and 19 Prod jobs. Existing paused jobs stay paused; existing Prod Jira jobs need destination/state migration, not duplicate schedules.
- Pub/Sub discovery found 17 UAT topics / nine subscriptions and nine Prod topics / nine subscriptions. Inventory routing and event-trigger dependencies before deploying consumers; deploying a Pub/Sub consumer can make it active immediately.
- Local discovery found 24 non-archived GAS folders. The root `.clasp.json` identifies only `VerificationTeamDatapipe`; its code feeds both verification performance tables. Local script folders are not proof of live deployments or active triggers.
- Live lookup initially returned HTTP 403. Follow-up on 2026-10-15 established expired clasp reauthentication and insufficient Apps Script scopes on the gcloud token (section 8.5); do not treat those responses as proof of missing script-owner access. Do not push source or install triggers until authorized Apps Script access, script IDs, trigger owners/schedules and script properties are verified. Trigger ownership requires an owner-side audit; copying source does not copy installed triggers or properties.
- Preserve both SHRPeople durable cycle state and Gmail processed-message state; do not copy credentials into source or inventory outputs.

The source-only seed helper is [seed_source_tables.ps1](../Temp/UAT_to_Prod_Migration/seed_source_tables.ps1). Its default mode validates without creating objects; execution refuses existing targets except explicitly owned baselines when resuming the same recorded run. It retains partition layout but does not introduce table/partition expiry during migration. Keep the run manifest outside the repository and do not rerun as a new seed over existing targets.

### 9.6.2 Approved Prod snapshot schedules activated (2026-10-14)

- All 26 approved EU scheduled-query copies are enabled: 24 CenterOps hourly schedules, `SR Count Record` at daily 20:00 UTC and `SHRPeople Monthly Snapshot Counts` at daily 00:00 UTC. All 26 original UAT configurations remain enabled and unchanged.
- Fresh outputs are `Dashboards.CenterOperationsShiftSnapshotsAgg` (DAY `Snapshot_Date`; `NOC, ShiftSnapshot, Actor_FullName`), `Dashboards.Active_SR_Count` (DAY `batch_date`; `sr_status`) and `Dashboards.SHRPeopleDailySnapshots` (`SR_Status, Circuit_Owner`). Historical dashboard snapshots were not copied.
- All 24 CenterOps schedules use the same verified query and differ only by schedule. One representative CenterOps run plus the two other query families passed actual DTS runs; the remaining 23 CenterOps copies were checked for identical query/routing, not each manually replayed. Manual validation adds timestamped snapshot batches to the new outputs; these are retained, not deleted.
- Queries read only fully qualified Prod `BMC` sources and explicitly `INSERT`/`MERGE` into existing clustered Prod output tables. Output layouts were rechecked after writes.
- Direct BigQuery query tests alone did not catch two DTS-specific failures: destination-table partition settings omitted the existing clustering, and a multi-statement SR query conflicted with a transfer-level destination dataset. All 26 copies were paused immediately. CenterOps was changed to explicit `INSERT` with named columns; the unnecessary SR table-creation statement was removed; transfer-level destination/partition settings were cleared. All three actual DTS query families then passed.
- Dedicated `dashboard-snapshots-runtime` has project BigQuery Job User, `BMC` reader and `Dashboards` writer grants. Final successful DTS jobs were explicitly checked through BigQuery job `user_email` and run as this service account, not the deploying user's credentials.
- [Project-owned deployment definition](../pccw-internal-virtual-agent/deployment.yaml) remains the canonical configuration. Dataset/table labels use `datacloud=vscode`; TransferConfig does not support `labels` and rejects that field, so attribution is applied to its destination dataset/tables and CLI environment instead.
- The installed orchestration framework parses YAML `metadata.serviceAccountName` (despite its handler description using `service_account_name`). Its update request also omits the credential field from `updateMask`, so setting metadata alone did not switch existing configs away from user credentials. [Scoped identity configuration](../Temp/UAT_to_Prod_Migration/configure_snapshot_identity.ps1) applies the API-required `updateMask=service_account_name` after deployment. Run it whenever changing authorization and verify actual job identity.

Deployment/verification order, using PowerShell and CLI/APIs only:

1. Generate the disabled definition with [prepare_snapshot_deployment.ps1](../Temp/UAT_to_Prod_Migration/prepare_snapshot_deployment.ps1) `-IncludeSchedules`.
2. From the Prod project folder, run `gcloud beta orchestration-pipelines validate --environment=prod --project=pccw-internal-virtual-agent`, then `gcloud beta orchestration-pipelines deploy --environment=prod --local --project=pccw-internal-virtual-agent --quiet`.
3. Run [validate_snapshot_schedules.ps1](../Temp/UAT_to_Prod_Migration/validate_snapshot_schedules.ps1) with a session-owned `-ResultPath` while configs are disabled. DTS refuses manual runs on disabled configs, so this stage runs the three query families directly as labelled, bounded BigQuery jobs.
4. After query/output validation, regenerate with `-IncludeSchedules -EnableSchedules`, validate/deploy, then run the scoped identity configuration.
5. Run snapshot validation with `-AllowEnabled -ResultPath ...` to test actual DTS execution and identity. Any validation exception in this mode pauses all 26 approved copies; leave them paused until the root cause is fixed.
6. Use [verify_parallel_resources.ps1](../Temp/UAT_to_Prod_Migration/verify_parallel_resources.ps1) for the scoped schedule/subscription/log inventory. It writes non-secret evidence outside the repository and flags failed natural push requests for review.

### 9.6.3 Paid-job move and final scoped schedule check (2026-10-15)

- All **26 Prod dashboard snapshot schedules remain enabled and now each has a successful latest DTS run**, including CenterOps hours 04/05/07/08 which previously had no run evidence. All 26 UAT snapshot originals remain unchanged. This is current execution evidence, not proof of several days of stability.
- Four paid Prod replacements were prepared paused, their UAT originals paused, and each replacement passed an actual controlled **zero-input DTS execution**. Single-input generation returned structured `ok`; single-input translation returned nonempty output with an empty row-level error status. No full paid inference batch was manually replayed; full natural-run stability remains to observe.
- After successful verification and the twelve UAT continuity-view changes, the four approved UAT paid configurations were deleted and absence read-back verified. Immediately before deletion, replacement full SQL, desired enabled/paused state and the successful recorded DTS run were rechecked; originals had to be unchanged, paused and have no pending/running runs.

| Paid schedule | Deleted UAT config ID | Prod config ID | Prod state |
|---|---|---|---|
| MSS AIInfused Daily Refresh | `6a1ea328-0000-26a9-95c8-001a114d3040` | `6b1d9b2e-0000-2d8c-bc09-001a114cbeb8` | Paused, preserving the original disabled state |
| HDWL AIInfused Daily Refresh | `6a298894-0000-26c8-880d-3c286d48384e` | `6ae3003e-0000-2770-ae83-94eb2c1fd7d0` | Enabled; Prod-only paid writer |
| CCAI_Dialogflow_Translation_Bi-Weekly | `6a99fd9c-0000-2501-a6ea-001a114d5056` | `6adb49cd-0000-20d0-af26-883d24fe2564` | Enabled; canonical cached translation writer |
| CCAI_Dialogflow_Translation_Weekly | `6ac3300e-0000-29e0-82ce-3c286d3bcd06` (US) | `6ad461c3-0000-2827-9c29-3c286d4418de` | Moved to EU but paused to avoid a competing translation writer |

- Prod API resource paths use project number `370161436243` and location `europe`; deleted UAT paths use `14417857267`, with the weekly legacy config formerly in `us`. Display names use `Prod - `. [Paid-job migration](../Temp/UAT_to_Prod_Migration/move_paid_schedules.cjs) retains original definitions, source/target resource names and controlled-run proofs outside the repository.
- Translation transfer credentials changed from the original owner to the deploying user; this was recorded and actual DTS authorization tested. This is not a service-account identity migration. Snapshot schedules continue using their separately verified `dashboard-snapshots-runtime` identity.
- The Prod [translation model](../pccw-internal-virtual-agent/BigQuery/wanda_ds/models/translation_model.sql) uses `REMOTE WITH CONNECTION DEFAULT` and `CLOUD_AI_TRANSLATE_V3`. Its connection is `projects/pccw-internal-virtual-agent/locations/eu/connections/__default_cloudresource_connection__`. Connection service account `bqcx-370161436243-07bs@gcp-sa-bigquery-condel.iam.gserviceaccount.com` required `roles/serviceusage.serviceUsageConsumer` on Prod; the grant was applied and the translation probe then succeeded. The pre-existing Vertex connection was not replaced.
- Four non-paid UAT refresh/copy configurations remain **unmigrated/requiring classification**: `Mirror Cost_Items Daily Copy`, `EDP-SR EU Copy`, `CostItemSnapSnapshot` and `EDP-SR-daily-mirror`. The first two write to UAT `Mirror`; do not blindly duplicate an entire dataset or classify them as Prod dashboard writers. The latter two run in `europe-west2`, while the new business replicas/views are EU. A scoped recurring cross-region refresh design is still needed for Prod cost/SR freshness.
- Ordinary UAT ingestion, non-paid schedules, source tables, models and connections were not deleted or disabled by this exception. Remaining gates include those business refreshes, the four blocked views, Drive access, application-agent cutover, multi-day pipeline/paid-run stability, genuine recovery and dashboard performance/connection cutover.

### 9.7 Step 5 — Snapshot pipeline & backup validation

- Run the Prod→UAT snapshot pipeline and verify the UAT snapshot matches Prod's current state (row counts + spot-check keys).
- Confirm the snapshot is a *reader* of Prod only; no direct writes to Prod from UAT.

### 9.8 Rollback checklist (data-loss first)

Every rollback path below must be fully testable before cutover and must be completable in under 30 minutes.

- **Pipeline:** switch `TARGET_PROJECT` back to UAT; re-enable the old scheduler. The old pipe keeps running during cutover, so flipping back is instantaneous.
- **View:** revert the view DDL to the last known-good version / point at the old dataset — the dashboard keeps working.
- **Scheduler:** disable the new Prod job; re-enable the old UAT job. Deleted paid configurations instead require recreation from archived definitions and fresh runtime authorization. Preserve/reconcile current Prod paid outputs and cache state before reverting continuity views; do not assume the frozen UAT tables are current or that the deleted resource IDs can be re-enabled.
- **Data:** if a Prod write went to the wrong place, stop that pipe, then reverse the load (replay UAT data into Prod or restore from the Prod snapshot) — the direction is always reversible.

### 9.9 Monitoring & alerts during cutover

- Alert on: pipeline errors, zero rows merged on a full run, view/query failures, dashboard "no data", and any data-count drift between Prod and UAT.
- Track end-to-end latency per pipeline.
- Track dashboard load time and representative query bytes processed, slot milliseconds and elapsed time against the agreed performance baseline.
- Keep a cutover board (table: pipe | phase | status | rollback trigger | owner).

### 9.10 Change management — hard constraint: no data loss of any kind

- Notify operations before the window; run outside peak hours; define a rollback SLA; log every decision in a change ticket.
- Any cutover step that cannot be proven safe against data loss is paused and escalated — do not proceed on faith.

### 9.11 Golden rules for zero data loss

- Never truncate in Prod without a verified, idempotent replacement in place.
- Never delete rows while a pipeline could still be writing them.
- Keep UAT a complete, restorable copy; treat it as disposable, never as loss-prone.
- If a step cannot be reversed, it cannot be started.
## 10. References

- `BigQuerySync/README.md` - object-definition sync (pull/push) between UAT and Prod projects.
- `Temp\wanda4.md` - planned BigQuery production migration and snapshot replication (roadmap).
- `KnowledgeBase/Wanda_Production_Architecture.md` - planned 4.0 production migration notes.
- `HANDOFF.md` section 7 - UAT and Prod BQ project facts.
