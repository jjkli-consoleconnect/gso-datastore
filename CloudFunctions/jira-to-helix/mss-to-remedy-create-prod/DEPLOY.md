# MSS-to-Helix Create (PROD) Deployment Guide

Last validated: 2026-08-17

This file is the production source of truth for `mss-to-remedy-create-prod`. Do not infer production settings from the UAT folder or old `Testing` dataset references.

## Current Production State

| Setting | Validated value |
|---|---|
| GCP project | `pccw-internal-virtual-agent` |
| Region | `europe-west2` |
| Function | `mss-to-remedy-create-prod` (Gen 2, Python 3.12) |
| Entry point | `jira_to_helix_create_prod` |
| Active revision after this change | `mss-to-remedy-create-prod-00021-xex` |
| Runtime service account | `jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com` |
| VPC connector | `eu-prod-wanda-vpc-conn` with all egress |
| Memory / timeout | `512MB` / `120s` |
| Production mode | `DRY_RUN=false` |
| Helix close PATCH | Disabled: `ENABLE_HELIX_CLOSE_PATCH=false` |
| BigQuery dataset | `pccw-internal-virtual-agent.jiratohelix` (`EU`) |

The revision name is historical evidence, not a deployment target. A later valid deployment will create a newer revision.

## What The Function Does

The operational destination is BMC Helix, not BigQuery.

1. Jira Automation sends an MSS issue, transition, or comment webhook.
2. The function maps Jira data to a Helix trouble ticket or worklog.
3. The function checks BigQuery ledger records to suppress webhook retries and duplicate Helix writes.
4. The function calls Helix through the VPC connector.
5. On ticket creation, the function writes the Helix incident ID back to a supported Jira Remedy field.
6. The function records successful or failed processing in the relevant BigQuery ledger.

The close-duplication workflow creates a new Helix ticket for a Jira close cycle and replays Jira comments. Its phase ledger allows retries to resume without repeating completed phases. The optional Helix close PATCH is disabled in production because the API rejects the supported status transitions; created tickets remain in the status assigned by Helix.

Malformed Jira Automation JSON is recovered by a loose parser. A recovered payload contains only partial issue data, so the function must hydrate the complete live Jira issue before event routing. A genuinely closed issue takes the close-duplication path unless Jira explicitly identifies the event as a comment event. Do not route solely because a recovered payload contains a `comment` object; the loose parser can synthesize that shape from a transition payload.

## BigQuery Ledgers

The dataset is intentionally named `jiratohelix`, not `MSStohelix`. If more Jira projects are added later, they should share this integration dataset unless isolation is explicitly required. Jira keys already include the project prefix, for example `MSS-8753`.

| Table | Purpose | Idempotency key |
|---|---|---|
| `jiratohelix.jira_to_helix_sync` | Ticket-create results and Jira-to-Helix ID mapping | `jira_key` with successful status |
| `jiratohelix.jira_to_helix_comment_sync` | Comment/worklog versions | Jira comment ID plus effective update timestamp, stored in `comment_id` |
| `jiratohelix.jira_to_helix_close_dup_sync` | Close-cycle create, comment replay, lock, and close phases | `jira_key` plus `phase_key` |

These tables are processing ledgers. They are not copies of complete Jira or Helix ticket data.

All three tables were explicitly created on 2026-08-17 before live deployment. Do not rely on first production traffic to create them. The comment and close tables use required field modes matching the proven UAT schemas.

Known validation artifact: `jira_to_helix_sync` contains one failed synthetic row for `MSS-DRYRUN`, created during staged testing at `2026-08-17 07:45:38 UTC`. It has no Helix ID and does not affect real Jira keys. It was deliberately not deleted without explicit approval.

## Environment Variables

The live function must have these as six separate values:

```text
DRY_RUN=false
ENABLE_HELIX_CLOSE_PATCH=false
JIRA_TO_HELIX_DATASET_ID=jiratohelix
JIRA_TO_HELIX_TABLE_ID=jira_to_helix_sync
JIRA_TO_HELIX_COMMENT_TABLE_ID=jira_to_helix_comment_sync
JIRA_TO_HELIX_CLOSE_DUP_TABLE_ID=jira_to_helix_close_dup_sync
```

Important PowerShell rule: quote the complete `--set-env-vars=...` argument. Without quotes, PowerShell/gcloud can store the entire comma-separated string as the value of `DRY_RUN`. That malformed value does not equal `"true"`, so the Python code treats it as live mode.

## IAM And Secrets

The runtime service account has:

- Dataset-level `WRITER` access on `pccw-internal-virtual-agent.jiratohelix`.
- Project-level `roles/bigquery.jobUser` to run parameterized idempotency queries. This role does not grant access to other dataset contents.
- Secret-level `roles/secretmanager.secretAccessor` on exactly these required secrets:
  - `jira-user-email`
  - `jira-api-token`
  - `PROD_HELIX_AUTH0_CLIENT_ID`
  - `PROD_HELIX_AUTH0_CLIENT_SECRET`
  - `PROD_HOST_NAME`

The `PROD_HOST_NAME` grant was missing before 2026-08-17 and was added during the staged rollout. The Helix client ID and client secret were originally stored as UTF-16LE and caused Python UTF-8 decode failures. UTF-8 versions were added as version `4`; older versions remain available for rollback.

## Dry-Run Contract

`DRY_RUN=true` must be non-mutating:

- No Helix create, GET, or PATCH request.
- No Jira field update.
- No BigQuery success or failure ledger write.
- No close-workflow cooldown lock write.
- No alert side effect from the top-level exception handler.
- Logging and BigQuery idempotency reads are allowed.

The code returns from Helix GET/PATCH helpers before Secret Manager access in dry-run mode. This behavior was added and smoke-tested on 2026-08-17.

## Safe Deployment Procedure

Never deploy a source or configuration change directly into live mode. Use this sequence:

1. Compile and check the source locally.
2. Confirm all three production tables exist and have the expected schemas.
3. Deploy with `DRY_RUN=true` and all four BigQuery identifiers explicitly set.
4. Describe the function and verify that environment variables appear as separate YAML keys.
5. Send a synthetic dry-run comment payload using a non-real Jira key and a supplied Remedy ID. Do not use a real Jira ticket for this check.
6. Confirm the response is HTTP 200 with `"status": "dry_run"`.
7. Confirm BigQuery row counts did not change and the revision has no error logs.
8. Verify all five secret-level IAM grants.
9. Deploy the same source with only `DRY_RUN=false` changed.
10. Confirm the Cloud Run service is ready and routes 100% traffic to the latest revision. Do not send a synthetic request after live mode is enabled.

Local preflight:

```powershell
& '.\.venv\Scripts\python.exe' -m py_compile 'CloudFunctions\jira-to-helix\mss-to-remedy-create-prod\main.py'
git -c core.whitespace=cr-at-eol diff --check -- 'CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/main.py' 'CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/DEPLOY.md'
```

PowerShell-safe deployment template:

```powershell
$env:CLOUDSDK_METRICS_ENVIRONMENT = 'datacloud.vscode'
gcloud functions deploy mss-to-remedy-create-prod `
  --gen2 `
  --runtime=python312 `
  --trigger-http `
  --entry-point=jira_to_helix_create_prod `
  --project=pccw-internal-virtual-agent `
  --region=europe-west2 `
  --service-account=jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com `
  --vpc-connector=projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn `
  --egress-settings=all `
  '--set-env-vars=DRY_RUN=true,ENABLE_HELIX_CLOSE_PATCH=false,JIRA_TO_HELIX_DATASET_ID=jiratohelix,JIRA_TO_HELIX_TABLE_ID=jira_to_helix_sync,JIRA_TO_HELIX_COMMENT_TABLE_ID=jira_to_helix_comment_sync,JIRA_TO_HELIX_CLOSE_DUP_TABLE_ID=jira_to_helix_close_dup_sync' `
  --source='CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/' `
  --timeout=120 `
  --memory=512MB `
  --quiet
```

After dry-run validation, repeat the exact command with only `DRY_RUN=true` changed to `DRY_RUN=false`.

## Adding More Jira Projects

Do not assume another Jira Automation rule is sufficient. The current implementation remains MSS-specific in several places:

- `JIRA_PROJECT = "MSS"` controls fallback Jira-key parsing.
- MSS custom field IDs and Remedy backlink candidates are hardcoded.
- The Helix customer/SR pair is forced to `TMSTKL` / `SR128190`. `TMSTKL` is the production Jira Customer ID; `TMS` is only the MSS customer label and is rejected by Helix SHR profile validation.
- Helix assignment defaults to `ASOC`.
- Jira status and close-duplication behavior are based on the MSS workflow.

Before adding another project, make project mapping explicit in configuration or code and add focused tests. The shared ledger tables can still be used. Consider adding a `jira_project` column for easier reporting, although the project can be derived from `jira_key`.

## UAT Mapping Parity

The business-approved UAT `map_jira_to_helix` function is the source of truth. Production mapping logic must remain structurally identical to UAT. Environment-specific constants may differ where Jira projects expose different field IDs or where endpoints, projects, and secrets differ.

Validated production field constants:

| Meaning | Production Jira field | Behavior |
|---|---|---|
| Customer ID, preferred | `customfield_16097` | `TMSTKL` on `MSS-8754`; shown as `Jira customer ID: TMSTKL` in the Helix description |
| MSS customer label, fallback | `customfield_11364` | `TMS`; used only when Customer ID is empty |
| SR Number | `customfield_10638` | Used for description trace when populated |
| SR Ref | `customfield_10382` | SR fallback for description trace |
| SP # / SR # | `customfield_11627` | SR fallback for description trace |

As in UAT, the Helix `relatedEntity` profile is explicitly forced to the validated default pair `TMSTKL/SR128190`. Jira customer/SR values are used for the source trace only. The mapping function's AST was compared with UAT before deploying revision `00019-poy`, and a deployed dry-run returned:

```text
customerId=TMSTKL
srId=SR128190
Jira customer ID: TMSTKL
Jira SR no: (not provided)
```

## Jira Comment Formatting

Jira comments use Atlassian Document Format (ADF). Inline formatting such as bold text splits one sentence into multiple adjacent `text` nodes. The previous shared formatter joined every text node with a newline, so bold fragments such as a time, product name, or username appeared on separate lines in Helix.

The formatter was corrected identically in UAT and production:

- Adjacent inline text nodes are concatenated exactly as Jira stores them.
- Paragraph and other block boundaries produce one newline.
- Explicit Jira `hardBreak` nodes produce one newline.
- Existing Remedy worklogs are not rewritten or replayed automatically.

The exact ADF pattern from Jira comment `1720252` on `MSS-8756` was validated locally and through production dry-run revision `00020-qaj`. The resulting worklog text kept `12:46:59`, `Crowdstrike`, and `gkorelis` inline while retaining the three intended paragraphs. Live revision `00021-xex` contains this fix. `MSS-8756` was not triggered or modified during validation.

## 2026-08-17 Incident And Resolution

Jira Automation audit event `ce01b2f8-6335-46b1-bebc-4b7d9defe32f` ran at `2026-08-17 15:14:36 +08:00` for `MSS-8753` and received HTTP 500:

```json
{"message":"Comment sync table unavailable","status":"error"}
```

Cloud Logging showed the root cause:

```text
404 Not found: Dataset pccw-internal-virtual-agent:Testing
```

The production project never had a `Testing` dataset. The similarly named tables existed only in UAT. Resolution:

- Created production EU dataset `pccw-internal-virtual-agent.jiratohelix`.
- Created all three ledger tables with schemas matching UAT.
- Granted narrow BigQuery dataset/query permissions to the runtime account.
- Pointed all production environment variables to `jiratohelix`.
- Fixed dry-run paths so validation cannot write ledgers or access Helix secrets/network.
- Added the missing `PROD_HOST_NAME` secret accessor grant.
- Validated in dry-run, then enabled live revision `00012-zob` with 100% traffic.

The original malformed Jira comment JSON was recovered by the function's loose parser. It was not the cause of the HTTP 500.

### 2026-08-17 16:41 +08:00 routing follow-up

Jira Automation audit event `a41da8fb-655c-49c5-8c36-7e8b03905f0a` ran for closed issue `MSS-8754` and received HTTP 400:

```json
{"comment_id":"10505","jira_key":"MSS-8754","message":"No Remedy ticket number found on Jira issue","status":"error"}
```

Cloud Logging showed that malformed JSON recovery had incorrectly routed the transition as a comment webhook. Jira API verification showed the issue was actually `Archived`, status category `done`, with `resolutiondate=2026-08-17T08:41:04.352Z` and no Remedy ID.

Resolution:

- Added explicit comment-event detection based on Jira event names.
- Hydrate malformed recovered payloads from the live Jira issue before routing.
- Route a closed issue to close duplication before considering a synthetic comment object, unless Jira explicitly declares a comment event.
- Made the close-workflow cooldown lock non-mutating in dry-run mode.
- Removed the redundant second close-routing branch.
- Replayed a truly malformed `MSS-8754` payload against dry-run revision `00013-bel`; it returned `status=dry_run`, replayed one comment, and left all ledger counts unchanged.
- Enabled live revision `00014-rut` after validation.

The failed comment-ledger row for `MSS-8754` remains harmless because idempotency checks only treat `sync_status='success'` as processed. Do not delete it without explicit approval.

### MSS-8754 authorized production replay

An explicitly authorized live replay exposed and resolved two additional production issues:

- `PROD_HELIX_AUTH0_CLIENT_ID` and `PROD_HELIX_AUTH0_CLIENT_SECRET` used UTF-16LE encoding. New UTF-8 secret versions were added as version `4` without deleting prior versions.
- Helix rejected `customerId=TMS` with `srId=SR128190` as an invalid SHR profile. Jira production field `Customer ID` (`customfield_16097`) contained `TMSTKL`, matching the proven UAT default. The production default was corrected to `TMSTKL`.
- Failed Helix creates previously left a cooldown lock in `in_progress`. The function now marks the lock and create phase failed when creation raises, allowing a controlled retry.

Final result:

- Jira issue: `MSS-8754`
- Helix ticket: `INC000011481347`
- Jira backlink: `customfield_10647=INC000011481347`
- External ID: `MSS-8754-C20260817084104`
- Jira comments replayed: `1` (`1720053`)
- Helix notes observed after replay: `4` (three create notes plus one Jira worklog)
- Helix status observed: `Acknowledged`
- Idempotency replay result: `duplicate_suppressed` with the same Helix ID

Helix rejected `CLOSED` as an invalid status and returned internal errors for `IN PROGRESS` and `RESOLVED`. Production now sets `ENABLE_HELIX_CLOSE_PATCH=false`; this prevents a misleading HTTP 500 after ticket creation, Jira backlink, and worklog replay have already succeeded.

## MSS Automation Setup (Production)

Production Jira is `https://consoleconnect.atlassian.net`. Do not connect the production function to the Jira sandbox.

The function supports three automation paths:

| Trigger | Required webhook content | Function behavior |
|---|---|---|
| Issue created | Issue key and fields | Create Helix ticket, replay existing Jira comments, and backlink Jira |
| Comment created or edited | Issue key, issue fields, and comment | Add a versioned Helix worklog |
| Issue transitioned to a configured closed state | Full issue payload with closed status | Run close-duplication workflow |

Every action must use HTTP `POST`, `Content-Type: application/json`, and include the issue data. An empty body returns `400 Invalid JSON payload`.

See [Jira to Helix Automation Admin Instructions](../../../KnowledgeBase/Jira_to_Helix_Automation_Admin_Instructions.md) for the validated close-transition rule, statuses, duplicate-prevention condition, and webhook URL. Keep Jira-side filters MSS-specific until the code has explicit per-project mappings.

## Monitoring

- Function: `https://console.cloud.google.com/functions/details/europe-west2/mss-to-remedy-create-prod?project=pccw-internal-virtual-agent`
- Logs: `https://console.cloud.google.com/logs/query?project=pccw-internal-virtual-agent`
- BigQuery ticket sync: `SELECT * FROM pccw-internal-virtual-agent.jiratohelix.jira_to_helix_sync ORDER BY created_timestamp DESC`
- BigQuery comment sync: `SELECT * FROM pccw-internal-virtual-agent.jiratohelix.jira_to_helix_comment_sync ORDER BY created_timestamp DESC`
- BigQuery close workflow: `SELECT * FROM pccw-internal-virtual-agent.jiratohelix.jira_to_helix_close_dup_sync ORDER BY created_timestamp DESC`

Gen 2 function logs use the Cloud Run revision resource. Reliable CLI query:

```powershell
$env:CLOUDSDK_METRICS_ENVIRONMENT = 'datacloud.vscode'
gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=mss-to-remedy-create-prod' `
  --project=pccw-internal-virtual-agent `
  --limit=100 `
  --order=desc `
  --format='value(timestamp,severity,httpRequest.status,textPayload,jsonPayload.message)'
```

Verify the deployed configuration after every deployment:

```powershell
gcloud functions describe mss-to-remedy-create-prod `
  --gen2 `
  --project=pccw-internal-virtual-agent `
  --region=europe-west2 `
  --format='yaml(serviceConfig.revision,serviceConfig.environmentVariables,serviceConfig.serviceAccountEmail,serviceConfig.vpcConnector,state)'
```

The environment-variable output must show six separate keys. Stop and correct the deployment immediately if `DRY_RUN` contains the other variable assignments in one long value.
