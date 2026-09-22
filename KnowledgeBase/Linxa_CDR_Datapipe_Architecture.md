# Linxa CDR Datapipe Architecture Notes

Planning note for a future Linxa CDR sync. No implementation exists yet.

## Confirmed API facts

- Base URL: `https://pccwg.linxa.com/api/connect`
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

- `CloudFunctions/pccw-internal-virtual-agent/JiraTicketsNightly/deploy.ps1`
- `CloudFunctions/pccw-internal-virtual-agent/JiraCommentsNightly/deploy.ps1`
- `CloudFunctions/pccw-internal-virtual-agent/JiraTickets/deploy.sh`
- `CloudFunctions/pccw-internal-virtual-agent/JiraComments/deploy.sh`
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

## Proposed Linxa sync design

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

## Open decisions before implementation

- Confirm target project, dataset, and table names.
- Confirm whether masked numbers are acceptable or whether `showMasked` must be false.
- Confirm report timezone used by Linxa filters.
- Confirm whether preset `284` is stable for production use.
- Confirm service account for UAT and prod.
- Confirm Secret Manager secret name for the Linxa API credential.
- Confirm desired retention and partitioning strategy in BigQuery.