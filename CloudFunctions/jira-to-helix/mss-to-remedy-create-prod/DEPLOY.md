# MSS-to-Helix Create (PROD) Deployment Guide

## Prerequisites
- Secrets configured in Secret Manager:
  - `jira-user-email`
  - `jira-api-token`
  - `PROD_HELIX_AUTH0_CLIENT_ID`
  - `PROD_HELIX_AUTH0_CLIENT_SECRET`
  - `PROD_HOST_NAME`

- BigQuery table created: `Testing.jira_to_helix_sync`
- BigQuery table (comment idempotency): `Testing.jira_to_helix_comment_sync` (auto-created by function on first comment event)
- VPC Connector ready: `eu-prod-wanda-vpc-conn`

## Current Validated Behavior
- Prod mirrors the UAT flow for create and comment handling, including the readable Jira source trace and metadata block in the Remedy description.
- Dry-run mode still fetches the live Jira issue but prevents writes to Helix and Jira.
- The validated create note pattern remains `category/item/type = Others`.
- The trigger URL accepts `?force=true` for safe re-drives during validation.

## Deploy Cloud Function

```bash
# From workspace root
gcloud functions deploy mss-to-remedy-create-prod \
  --gen2 \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point jira_to_helix_create_prod \
  --project pccw-internal-virtual-agent \
  --region europe-west2 \
  --service-account jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com \
  --vpc-connector projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn \
  --egress-settings all \
  --set-env-vars DRY_RUN=false,JIRA_TO_HELIX_DATASET_ID=Testing,JIRA_TO_HELIX_TABLE_ID=jira_to_helix_sync,JIRA_TO_HELIX_COMMENT_TABLE_ID=jira_to_helix_comment_sync \
  --source CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/ \
  --timeout 120 \
  --memory 512MB
```

For a safe validation pass after deploy, switch only `DRY_RUN` to `true`:

```bash
gcloud functions deploy mss-to-remedy-create-prod \
  --gen2 \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point jira_to_helix_create_prod \
  --project pccw-internal-virtual-agent \
  --region europe-west2 \
  --service-account jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com \
  --vpc-connector projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn \
  --egress-settings all \
  --update-env-vars DRY_RUN=true \
  --source CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/ \
  --timeout 120 \
  --memory 512MB
```

When dry-run is enabled, the function logs the would-post Helix payload and stops before Helix/Jira writes.

## MSS Automation Setup (Production)

1. Go: https://consoleconnect.atlassian.net
2. Settings -> Automations
3. Create issue-created rule:
   - Trigger: Issue Created
   - Filter: `project = MSS`
   - Action: Send web request (POST)
  - URL: deployed `mss-to-remedy-create-prod` trigger URL
   - Header: `Content-Type: application/json`
   - Body: default Jira webhook payload
4. Create issue-commented rule:
   - Trigger: Issue Commented
   - Filter: `project = MSS`
   - Action: Send web request (POST)
  - URL: deployed `mss-to-remedy-create-prod` trigger URL
   - Header: `Content-Type: application/json`
   - Body: default Jira webhook payload (must include `issue` and `comment`)

## Monitoring

- Logs: `https://console.cloud.google.com/logs/query?project=pccw-internal-virtual-agent&resource=cloud_function&filter=resource.labels.function_name="mss-to-remedy-create-prod"`
- BigQuery ticket sync: `SELECT * FROM pccw-internal-virtual-agent.Testing.jira_to_helix_sync ORDER BY created_timestamp DESC`
- BigQuery comment sync: `SELECT * FROM pccw-internal-virtual-agent.Testing.jira_to_helix_comment_sync ORDER BY created_timestamp DESC`
