# Handover: BigQuery → Draw.io → Confluence Data Lineage Pipeline

## Goal
Deploy the BigQuery → Draw.io → Confluence data lineage pipeline as a GCP Cloud Function in production (`pccw-internal-virtual-agent`), aligned with existing Cloud Function patterns.

## Current State

### Cloud Function: `data_lineage_sync`
- **Project:** `pccw-internal-virtual-agent`
- **Region:** `europe-west2`
- **Runtime:** `python311`
- **Version:** 7 (1st gen)
- **Status:** OFFLINE (expected for 1st gen Pub/Sub-triggered functions until first invocation)
- **Trigger:** Pub/Sub topic `lineage-sync`
- **Entry point:** `main`
- **Source:** `pccw-internal-virt-agent-uat/CloudFunctions/data_lineage/`

### Secrets Mounted (all 6)
| Env Var / Secret | Status |
|---|---|
| `GCP_PROJECT_ID` | ✅ env var set to `pccw-internal-virtual-agent` |
| `GCP_SA_KEY` | ✅ secret mounted |
| `CONFLUENCE_API_TOKEN` | ✅ secret mounted |
| `CONFLUENCE_DOMAIN` | ✅ secret mounted |
| `CONFLUENCE_PAGE_ID` | ✅ secret mounted |
| `CONFLUENCE_USER_EMAIL` | ✅ secret mounted |

### Service Account
- `pccw-internal-virtual-agent@appspot.gserviceaccount.com`
- Has `roles/secretmanager.secretAccessor` granted

### Pub/Sub
- **Topic:** `lineage-sync` ✅ created
- **Subscription:** `data_lineage_sync_sub` ✅ manually created (push to function URL)
- **Note:** Cloud Functions did NOT auto-create a subscription. Manual subscription created pointing to `https://europe-west2-pccw-internal-virtual-agent.cloudfunctions.net/data_lineage_sync`

### Cloud Scheduler
- **Job:** `data-lineage-schedule`
- **Schedule:** Daily 2 AM UTC
- **State:** ENABLED
- **Target:** Pub/Sub topic `lineage-sync`

## Problem: Function is OFFLINE / Not Serving

The 1st gen Cloud Function shows OFFLINE and returns 404 on its public URL. This is because:

1. **1st gen Pub/Sub-triggered functions don't expose a public HTTP endpoint.** The URL `https://europe-west2-pccw-internal-virtual-agent.cloudfunctions.net/data_lineage_sync` returns 404.
2. **Cloud Functions did not auto-create a Pub/Sub subscription.** Even though `--trigger-topic lineage-sync` was specified, no subscription was created by Cloud Functions.
3. **Manually created subscription pushes to a non-existent URL.** The push subscription `data_lineage_sync_sub` points to the public function URL which doesn't serve.

## Root Cause
The manual Pub/Sub subscription approach doesn't work for 1st gen functions because they don't have public HTTP endpoints for Pub/Sub triggers. Cloud Functions handles Pub/Sub invocation internally.

## Recommended Fix

### Option A: Switch to 2nd Gen HTTP Trigger (Recommended)

1. **Modify `main.py`**: Change `@functions_framework.cloud_event` to `@functions_framework.http` and update function signature from `main(cloud_event)` to `main(request)`.
2. **Remove `cloud_event.data` parsing** if any (check full code).
3. **Deploy as 2nd gen HTTP trigger:**
   ```bash
   gcloud functions deploy data_lineage_sync \
     --region europe-west2 \
     --project pccw-internal-virtual-agent \
     --runtime python311 \
     --gen2 \
     --trigger-http \
     --entry-point main \
     --source C:/dev/gso-datastore/pccw-internal-virt-agent-uat/CloudFunctions/data_lineage \
     --set-secrets "GCP_SA_KEY=projects/pccw-internal-virtual-agent/secrets/GCP_SA_KEY/versions/latest,CONFLUENCE_API_TOKEN=projects/pccw-internal-virtual-agent/secrets/CONFLUENCE_API_TOKEN/versions/latest,CONFLUENCE_DOMAIN=projects/pccw-internal-virtual-agent/secrets/CONFLUENCE_DOMAIN/versions/latest,CONFLUENCE_PAGE_ID=projects/pccw-internal-virtual-agent/secrets/CONFLUENCE_PAGE_ID/versions/latest,CONFLUENCE_USER_EMAIL=projects/pccw-internal-virtual-agent/secrets/CONFLUENCE_USER_EMAIL/versions/latest" \
     --set-env-vars "GCP_PROJECT_ID=pccw-internal-virtual-agent" \
     --allow-unauthenticated
   ```
4. **Update Cloud Scheduler** to use HTTP trigger instead of Pub/Sub:
   - Delete existing job: `gcloud scheduler jobs delete data-lineage-schedule --location europe-west2 --project pccw-internal-virtual-agent`
   - Create new HTTP job pointing to the function URL

### Option B: Fix 1st Gen Pub/Sub Subscription

1. Delete the manual subscription: `gcloud pubsub subscriptions delete data_lineage_sync_sub --project pccw-internal-virtual-agent`
2. Redeploy the function (may need to delete and recreate) — Cloud Functions should auto-create the subscription.
3. If auto-creation fails, the 1st gen function may need to be deployed via Console UI instead of CLI.

## Key Files

| File | Purpose |
|---|---|
| `pccw-internal-virt-agent-uat/CloudFunctions/data_lineage/main.py` | Function source (entry point `main`) |
| `pccw-internal-virt-agent-uat/CloudFunctions/data_lineage/requirements.txt` | Python dependencies |
| `main.py` (root) | Fallback copy of function source |
| `requirements.txt` (root) | Fallback copy of dependencies |

## Notes

- The 1st gen function currently has all 6 secrets/env vars mounted (version 7).
- The `CONFLUENCE_USER_EMAIL` secret name matches code expectation (`CONFLUENCE_USER_EMAIL`).
- Deploy commands timeout at 30s due to Docker builds — run from terminal with no timeout.
- All other functions in this project use 2nd gen HTTP triggers (see `gcloud functions list` output).
- Code uses `functions_framework.cloud_event` decorator — needs change to `functions_framework.http` for 2nd gen HTTP.

## Repo Structure Note
User flagged that prod code sits under `pccw-internal-virt-agent-uat/CloudFunctions/` which is confusing. Consider moving to `pccw-internal-virtual-agent/CloudFunctions/data_lineage/` to match prod project name. All existing Cloud Functions follow the uat folder pattern though.
