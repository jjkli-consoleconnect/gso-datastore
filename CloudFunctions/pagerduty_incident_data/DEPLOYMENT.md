# PagerDuty Incident Data Pipeline - Deployment Guide

## Prerequisites

- GCP Project: `pccw-internal-virt-agent-uat`
- PagerDuty API token (from PagerDuty Admin → API Access)
- gcloud CLI installed and authenticated
- BigQuery dataset: `GSO` (should already exist)

## Step 1: Store PagerDuty API Token in Secret Manager

```bash
# Set your PagerDuty API token
PAGERDUTY_TOKEN="your_actual_token_here"

# Create the secret
echo -n "$PAGERDUTY_TOKEN" | gcloud secrets create pagerduty-api-token \
  --replication-policy="automatic" \
  --data-file=-

# Verify it was created
gcloud secrets list | grep pagerduty
```

## Step 2: Grant Cloud Functions Service Account Access to Secret

```bash
# Grant the Cloud Functions default service account access
gcloud secrets add-iam-policy-binding pagerduty-api-token \
  --member=serviceAccount:pccw-internal-virt-agent-uat@appspot.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

## Step 3: Create/Verify BigQuery Dataset

```bash
# Create dataset if it doesn't exist
bq mk --dataset \
  --location=US \
  --description="GSO Data warehouse" \
  pccw-internal-virt-agent-uat:GSO

# Verify it exists
bq ls -d pccw-internal-virt-agent-uat:GSO
```

## Step 4: Create PipelineRuns Table (if not exists)

```bash
bq mk --table \
  --schema PipelineName:STRING,RunID:STRING,RunTime:TIMESTAMP,WindowStart:TIMESTAMP,WindowEnd:TIMESTAMP,RowsMerged:INTEGER,LogLevel:STRING,Message:STRING,Status:STRING,ErrorCode:STRING,DurationSeconds:FLOAT64,Context:JSON \
  --clustering_fields PipelineName,RunTime \
  pccw-internal-virt-agent-uat:GSO.PipelineRuns
```

## Step 5: Deploy the Cloud Function

```bash
cd CloudFunctions/pagerduty_incident_data

gcloud functions deploy sync_pagerduty_incidents \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source . \
  --entry-point sync_pagerduty_incidents \
  --trigger-http \
  --allow-unauthenticated \
  --memory 512MB \
  --timeout 540s \
  --environment-variables GOOGLE_CLOUD_PROJECT=pccw-internal-virt-agent-uat
```

**Note**: Adjust `--region` as needed for your deployment region.

## Step 6: Get the Cloud Function URL

```bash
# After deployment, get the function's URL
gcloud functions describe sync_pagerduty_incidents \
  --gen2 \
  --region us-central1 \
  --format='value(serviceConfig.uri)'
```

This will output something like:
```
https://us-central1-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_pagerduty_incidents
```

Save this URL for testing and scheduling.

## Step 7: Perform Initial Full Data Pull

```bash
# Set your function URL
CF_URL="https://your-region-your-project.cloudfunctions.net/sync_pagerduty_incidents"

# Run the full pull (this will take a few minutes)
curl -X POST "${CF_URL}?full_pull=true"

# Check the response for success
# Should see: {"status": "success", "sync_type": "full", ...}
```

## Step 8: Verify Data in BigQuery

```bash
# Check the incident data was loaded
bq query --use_legacy_sql=false '
SELECT 
  COUNT(*) as total_incidents,
  COUNT(DISTINCT incident_number) as unique_incidents,
  MAX(sync_time) as latest_sync
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`
'

# Check the pipeline run log
bq query --use_legacy_sql=false '
SELECT 
  RunTime,
  Status,
  RowsMerged,
  DurationSeconds,
  Message
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE PipelineName = "PagerDutyIncidentData"
ORDER BY RunTime DESC
LIMIT 5
'
```

## Step 9: Set Up Cloud Scheduler for Hourly Incremental Syncs

```bash
# Create a Cloud Scheduler job for hourly delta pulls
gcloud scheduler jobs create http pagerduty-incidents-hourly \
  --location us-central1 \
  --schedule "0 * * * *" \
  --uri "https://your-region-your-project.cloudfunctions.net/sync_pagerduty_incidents" \
  --http-method GET \
  --tz "UTC" \
  --message-body ""

# Verify the job was created
gcloud scheduler jobs list --location us-central1 | grep pagerduty

# You can trigger it manually:
gcloud scheduler jobs run pagerduty-incidents-hourly --location us-central1
```

## Step 10: Optional - Set Up Monitoring & Alerts

### Create a Cloud Logging Alert for Failed Syncs

```bash
gcloud alpha monitoring policies create \
  --notification-channels=YOUR_CHANNEL_ID \
  --display-name="PagerDuty Pipeline Failed" \
  --condition-display-name="Pipeline status is FAILED" \
  --condition-threshold-filter='
    resource.type="cloud_function"
    AND log_name="projects/pccw-internal-virt-agent-uat/logs/cloudfunctions.googleapis.com"
    AND jsonPayload.pipeline_name="PagerDutyIncidentData"
    AND jsonPayload.status="FAILED"
  ' \
  --condition-threshold-duration=300s
```

## Verification Checklist

- [ ] Secret `pagerduty-api-token` exists in Secret Manager
- [ ] Service account has access to the secret
- [ ] Cloud Function deployed successfully
- [ ] Full pull completed with data in `GSO.PagerDutyIncidentData`
- [ ] Pipeline run logged in `GSO.PipelineRuns`
- [ ] Cloud Scheduler job created for hourly runs
- [ ] Can query data in BigQuery

## Troubleshooting Deployment

### Function deployment fails with "NO_TOKEN"
```bash
# 1. Verify the secret exists
gcloud secrets list

# 2. Verify service account has access
gcloud secrets get-iam-policy pagerduty-api-token

# 3. Get the Cloud Function's service account
gcloud functions describe sync_pagerduty_incidents --gen2 --region us-central1 \
  --format='value(serviceConfig.serviceAccountEmail)'

# 4. Grant access if needed
gcloud secrets add-iam-policy-binding pagerduty-api-token \
  --member=serviceAccount:SERVICE_ACCOUNT_EMAIL \
  --role=roles/secretmanager.secretAccessor
```

### Function times out (>540s)
- Reduce `hours_back` parameter (fewer incidents to fetch)
- For full pulls, they may take longer; this is normal

### BigQuery table creation fails
- Ensure `GSO` dataset exists: `bq ls pccw-internal-virt-agent-uat:`
- Verify your service account has BigQuery Editor role

### Data not appearing in table
1. Check pipeline runs: `SELECT * FROM GSO.PipelineRuns WHERE PipelineName = "PagerDutyIncidentData"`
2. Check Cloud Function logs: `gcloud functions describe sync_pagerduty_incidents`
3. Check for errors in the function response

## Rollback Procedure

If you need to rollback the function:

```bash
# Delete the current function
gcloud functions delete sync_pagerduty_incidents --gen2 --region us-central1

# Optionally restore from a previous version
gcloud functions list-runtimes | grep python

# Redeploy with previous code
cd CloudFunctions/pagerduty_incident_data
gcloud functions deploy sync_pagerduty_incidents --gen2 --runtime python311 ...
```

## Next Steps

1. After initial full pull, data will synced hourly
2. Set up BigQuery views for team-specific dashboards
3. Create Data Studio dashboards from the data
4. Monitor performance metrics and set SLAs
5. Consider additional enrichment (Jira tickets, other incident data)
