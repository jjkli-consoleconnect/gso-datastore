# Linxa CDR Datapipe Architecture Notes

Planning note for a future Linxa CDR sync. No implementation exists yet.

## Confirmed API facts

- Base URL: `https://pccwg.linxa.com/api/connect`
- Saved Report Builder endpoint: `POST /v1/report-builder/getReport`.
- CDR Archive endpoint: `POST /v1/cdr-archive/getSummaryReport`; this is a different report surface and should not be used for a saved Report Builder preset.
- UAT credential is stored as Secret Manager secret `linxa-api-authorization` in project `pccw-internal-virt-agent-uat`. Retrieve server-side only; never pass the value to an LLM.
- Report Builder preset `2756` returned HTTP `200` through `getReport` with the UAT credential and an object containing `dataList`.
- The Report Builder response contained 10,000 aggregate objects even when `range.length=1`; `range.start=10000` returned the same first result. Pagination is not verified and may be ignored.
- The Report Builder result fields included `ASR`, `Destination`, `ACD`, `Outgoing_Carrier`, `Incoming_Trunk`, `Incoming_Account`, `Successful_Calls`, `Unsuccessful_Calls`, `Call_Attempts`, `Incoming_Carrier`, `Outgoing_Account`, `Outgoing_Trunk`, `Destination_Country`, `NER`, `Duration_(Minutes)`, and `Answered_Calls`.
- The date window sent to Report Builder was not independently verified because returned records did not expose a date field. Validate against Linxa UI or a known low-volume date before presenting date-labeled totals.
- CDR endpoint tested: `POST /v1/cdr-archive/getSummaryReport`
- Working preset tested: `284`
- Service type tested: `V`
- Response shape: JSON array where row 0 is the header row and subsequent rows are data rows.
- Preset `284` returns 33 columns, including `CDR ID`, `Call Start`, `Finish`, `Duration (sec)`, `Duration (min)`, carrier names, carrier IDs, status code, and SIP response code.
- One-day sync for `2026-09-09` returned at least 10,000 rows; 1,000-row pages were about 0.43 MB each.
- High offset paging can be slow and unreliable; offset `10000` worked, while deeper sparse offsets returned `403` during probing.

## Network requirement

- `pccwg.linxa.com` resolves to private address `172.27.12.11`.
- The current workstation can reach TCP 443.
- A deployed Cloud Function should use the same VPC connector pattern as the Jira datapipes to reach the private Linxa API.

## Existing Jira VPC pattern to replicate

Canonical examples:

- `pccw-internal-virtual-agent/CloudFunctions/JiraTicketsNightly/deploy.ps1`
- `pccw-internal-virtual-agent/CloudFunctions/JiraCommentsNightly/deploy.ps1`
- `pccw-internal-virtual-agent/CloudFunctions/JiraTickets/deploy.sh`
- `pccw-internal-virtual-agent/CloudFunctions/JiraComments/deploy.sh`
- `KnowledgeBase/VPC_UAT.md`

Shared deployment shape:

- Cloud Functions Gen2
- Runtime: `python311` in existing Jira pipes
- Region: `europe-west2`
- Trigger: HTTP
- VPC connector passed as a fully qualified path:
  - UAT: `projects/pccw-internal-virt-agent-uat/locations/europe-west2/connectors/eu-uat-wanda-vpc-conn`
  - Prod: `projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn`
- Egress: `--egress-settings all`
- Auth: `--no-allow-unauthenticated` by default
- Runtime service account:
  - UAT Jira example: `jira-bigquery@pccw-internal-virt-agent-uat.iam.gserviceaccount.com`
  - Prod Jira example: `jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com`
- Secrets should come from Secret Manager, not source files.
- Long-running sync functions use larger resource limits, for example `--timeout 3600s`, `--memory 2048Mi`, `--max-instances 5` in the nightly Jira pipes.

## Proposed Linxa ADK/reporting design

The chatbot must not connect directly from the model to Linxa. Implement a server-side ADK tool or backend service that owns credentials, network access, request validation, and response-size limits.

```text
User -> ADK agent -> get_linxa_saved_report tool (server-side)
                         -> Secret Manager credential
                         -> VPC-routed HTTPS request to Linxa
                         -> validate and reduce response
                         -> return authorized report data to agent
```

Tool requirements:

- Read `linxa-api-authorization` from Secret Manager at runtime using the workload service account.
- Send its raw configured value in the `Authorization` header as supplied; do not prepend `Bearer ` unless the credential is a JWT and Linxa requires it.
- Allow only approved report IDs, initially including Report Builder preset `2756` if approved for the target environment.
- Call `POST /v1/report-builder/getReport` for Report Builder presets.
- Never route a Report Builder preset to `/v1/cdr-archive/getSummaryReport`.
- Keep secrets out of model prompts, tool parameters, tool results, session state, logs, and user-visible errors.
- Default to masked data and return a bounded result or aggregate rather than blindly returning a large `dataList` to the model.
- Verify date filtering, limits, and pagination against Linxa before claiming complete date-specific results.
- Enforce user authorization server-side before making the Linxa request.

### Report Builder request probe

The tested request shape was:

```json
{
  "presetId": "2756",
  "serviceType": "V",
  "showMasked": true,
  "metrics": ["ATTEMPTS", "ASR", "ACD", "DURATION"],
  "groupBy": ["START_DATE", "COUNTRY"],
  "startDate": "2026-09-27T00:00:00Z",
  "endDate": "2026-09-27T23:59:59Z",
  "filters": {
    "from": "2026-09-27 00:00",
    "to": "2026-09-27 23:59",
    "successfulCallsOnly": false
  }
}
```

Response shape: JSON object with `dataList`, an array of objects. The probe returned 10,000 objects, and the offset range fields did not page the data. Treat the response as potentially capped or unbounded until Linxa documents the behavior. The request included date fields, but returned data did not prove that those filters were applied.

### CDR Archive flow

Use this only when the user needs CDR archive rows, not a saved Report Builder report. The tested endpoint is `POST /v1/cdr-archive/getSummaryReport`; it accepts `presetId`, `serviceType`, `showMasked`, `filters.from`/`filters.to`, and `range`. Presets `264`/`284` returned rows in earlier tests. Report Builder preset `2756` returned `Preset does not exists` on this endpoint with the UAT credential, confirming that preset IDs must not be treated as interchangeable across endpoints.

For CDR Archive, the response is a JSON array with the header row at index 0 followed by record rows. Use bounded date windows, mask numbers, and do not pass raw rows to the LLM unless each user is authorized and the use case requires it.

## Proposed scheduled Linxa CDR sync design

1. Cloud Scheduler triggers the function once daily.
2. Function computes the previous complete day in Linxa local/report time.
3. Function splits the day into smaller windows, preferably hourly or 30-minute chunks, to avoid deep offset paging.
4. For each window, call `getSummaryReport` with:

```json
{
  "presetId": "284",
  "serviceType": "V",
  "showMasked": true,
  "filters": {
    "from": "YYYY-MM-DD HH:mm",
    "to": "YYYY-MM-DD HH:mm"
  },
  "range": {
    "start": 0,
    "length": 1000
  }
}
```

5. Continue paging each window until fewer than the requested page size is returned.
6. Load raw rows into a BigQuery staging table.
7. Merge into a final table using `CDR ID` as the primary dedupe key.
8. Log every run with the repo's existing `setup_root_logging` plus `PipelineRuns` pattern.

The saved Report Builder endpoint is a separate option for preset-backed report output. Do not base a daily ETL on it until date filtering, output caps, pagination, and repeatability are validated.

## Open decisions before implementation

- Confirm target project, dataset, and table names.
- Confirm whether masked numbers are acceptable or whether `showMasked` must be false.
- Confirm report timezone used by Linxa filters.
- Confirm whether preset `284` is stable for production use.
- Confirm service account for UAT and prod.
- Confirm Secret Manager secret name for the Linxa API credential.
- Confirm desired retention and partitioning strategy in BigQuery.