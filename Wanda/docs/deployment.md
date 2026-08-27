# Wanda Web Deployment Guide

## Safety Rules

- Deploy only the `wanda-web` Cloud Run service for web UI or analyst-proxy
	changes. Do not deploy or modify `wanda-adk-slack-webhook` or other webhook
	services for this work.
- Pull the current Cloud Run build source before editing. The workspace copy can
	be stale.
- Keep the existing revision available for rollback. Do not delete the global
	GSO agent during an EU migration.

## Pull Current UAT Source

Run from PowerShell:

```powershell
$env:CLOUDSDK_METRICS_ENVIRONMENT = 'datacloud.vscode'
$project = 'pccw-internal-virt-agent-uat'
$service = gcloud run services describe wanda-web --project=$project --region=europe-west2 --format="value(metadata.annotations['run.googleapis.com/build-source-location'])"
$root = 'g:\My Drive\Scripts\Temp\wanda-web-uat-current'
New-Item -ItemType Directory -Path $root -Force | Out-Null
gcloud storage cp $service "$root\source.zip" --quiet
Expand-Archive "$root\source.zip" "$root\source" -Force
```

The active source contains `Dockerfile`, `server.js`, and `index.html`. It is a
Node.js service; do not replace it with a static Nginx deployment because the
analyst proxy requires Cloud Run runtime credentials.

## Validate Before Deployment

```powershell
Set-Location 'g:\My Drive\Scripts\Temp\wanda-web-uat-current\source'
node --check server.js
docker build --pull --tag wanda-web-uat-candidate .
docker run --rm -p 8080:8080 wanda-web-uat-candidate
```

For analyst changes, test both EU agents directly and through the local
`/api/data-agent/chat/stream` route. A successful direct API call alone does
not prove the Cloud Run runtime service account can query source data.

## Deploy UAT

```powershell
$env:CLOUDSDK_METRICS_ENVIRONMENT = 'datacloud.vscode'
Set-Location 'g:\My Drive\Scripts\Temp\wanda-web-uat-current\source'
gcloud run deploy wanda-web --source . --project=pccw-internal-virt-agent-uat --region=europe-west2 --quiet
```

Confirm the revision and traffic after deployment:

```powershell
gcloud run services describe wanda-web --project=pccw-internal-virt-agent-uat --region=europe-west2 --format='value(status.latestReadyRevisionName,status.traffic[0].revisionName,status.traffic[0].percent,status.url)'
```

Expected result: the latest revision has `100` percent traffic.

## IAM Preflight for a New Analyst

Before wiring a new analyst into the web UI, check all three layers:

1. `geminidataanalytics.googleapis.com` is enabled in UAT.
2. The runtime service account has `roles/geminidataanalytics.dataAgentUser` on
	 the agent resource.
3. The runtime service account has `roles/bigquery.jobUser` in every source
	 project plus `READER` on every referenced dataset.

For Ops data, the source project is `pccw-internal-virtual-agent` and the
datasets are `AgentDataset` and `LookerStudio`.

After granting IAM, test a fresh conversation through the live browser. Query
failures can otherwise look like an empty stream because the analytics API may
emit planning events but no final response when an underlying BigQuery table is
denied.

## Rollback

List revisions, then route traffic back to the last known-good revision:

```powershell
gcloud run revisions list --service=wanda-web --project=pccw-internal-virt-agent-uat --region=europe-west2
gcloud run services update-traffic wanda-web --project=pccw-internal-virt-agent-uat --region=europe-west2 --to-revisions=REVISION_NAME=100
```

Use rollback for application defects. Do not use it to conceal a data-access
failure; correct the missing agent or BigQuery IAM instead.
