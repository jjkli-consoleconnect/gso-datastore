# PagerDuty Incident Data Pipeline - Quick Start Guide

🚀 **Get this running in 30 minutes**

---

## Prerequisites

- ✅ Google Cloud SDK (`gcloud`) installed
- ✅ PagerDuty API token (from Settings → API Access → API key)
- ✅ Project: `pccw-internal-virt-agent-uat`
- ✅ BigQuery dataset: `GSO` (exists)

---

## Step 1: Store Your API Token (2 minutes)

```bash
# Replace with your actual PagerDuty API token
export PAGERDUTY_TOKEN="REDACTED"

# Create the secret
echo -n "$PAGERDUTY_TOKEN" | gcloud secrets create pagerduty-api-token --data-file=-

# Verify
gcloud secrets list | grep pagerduty
```

---

## Step 2: Grant Service Account Access (1 minute)

```bash
# This gives the Cloud Functions service account permission to read the secret
gcloud secrets add-iam-policy-binding pagerduty-api-token \
  --member=serviceAccount:pccw-internal-virt-agent-uat@appspot.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# Verify
gcloud secrets get-iam-policy pagerduty-api-token
```

---

## Step 3: Deploy the Cloud Function (5 minutes)

```bash
cd CloudFunctions/pccw-internal-virt-agent-uat/pagerduty_incident_data

# Deploy
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
  --set-env-vars GOOGLE_CLOUD_PROJECT=pccw-internal-virt-agent-uat

# Watch the deployment
# Should see: "httpsTrigger: {url: https://...}"
```

---

## Step 4: Get the Function URL (1 minute)

```bash
gcloud functions describe sync_pagerduty_incidents \
  --gen2 \
  --region us-central1 \
  --format='value(serviceConfig.uri)'

# Output will look like:
# https://us-central1-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_pagerduty_incidents

# Save this URL
export CF_URL="YOUR_URL_HERE"
```

---

## Step 5: Run Full Data Pull (5-10 minutes)

```bash
# This fetches all your PagerDuty incidents and loads them into BigQuery
curl -X POST "${CF_URL}?full_pull=true"

# Watch it run
# You should see JSON response like:
# {"status":"success","incidents_synced":45,"sync_type":"full",...}
```

---

## Step 6: Verify Data Loaded (2 minutes)

```bash
# Check how many incidents were loaded
bq query --use_legacy_sql=false '
SELECT 
  COUNT(*) as total_incidents,
  COUNT(DISTINCT incident_number) as unique_incidents,
  MAX(sync_time) as latest_sync,
  MIN(created_at) as oldest_incident
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`
'

# Check pipeline run logs
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

---

## Step 7: Schedule Hourly Syncs (3 minutes)

```bash
# Create a Cloud Scheduler job to run hourly
gcloud scheduler jobs create http pagerduty-incidents-hourly \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --uri="${CF_URL}" \
  --http-method=GET \
  --tz="UTC"

# Test it
gcloud scheduler jobs run pagerduty-incidents-hourly --location=us-central1

# List jobs
gcloud scheduler jobs list --location=us-central1
```

---

## ✅ You're Done!

Your pipeline is now:
- ✅ Running your first full pull (all historical incidents)
- ✅ Scheduled for hourly incremental updates
- ✅ Logging pipeline runs for monitoring
- ✅ Data clustered for fast queries

---

## 🎯 Next: Basic Queries

### See incident by escalation policy
```sql
SELECT 
  escalation_policy_name, 
  COUNT(*) as incidents
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`
WHERE resolved_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY escalation_policy_name
ORDER BY incidents DESC
```

### Average resolution time
```sql
SELECT
  escalation_policy_name,
  AVG(time_to_resolve_seconds) / 60 as avg_ttr_minutes,
  COUNT(*) as incident_count
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`
WHERE resolved_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY escalation_policy_name
ORDER BY avg_ttr_minutes DESC
```

### Incidents by service
```sql
SELECT
  service_name,
  COUNT(*) as incident_count,
  COUNTIF(urgency = 'high') as critical,
  DATE(created_at) as date
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY service_name, date
ORDER BY date DESC
```

---

## 🆘 Troubleshooting

### "Failed to retrieve API token"
```bash
# Check secret exists
gcloud secrets list

# Check service account has access
gcloud secrets get-iam-policy pagerduty-api-token

# Fix access
gcloud secrets add-iam-policy-binding pagerduty-api-token \
  --member=serviceAccount:pccw-internal-virt-agent-uat@appspot.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

### "Failed to create table"
```bash
# Make sure GSO dataset exists
bq ls pccw-internal-virt-agent-uat:

# If not, create it
bq mk --dataset --location=US pccw-internal-virt-agent-uat:GSO
```

### No data appearing
```bash
# Check logs
gcloud functions logs read sync_pagerduty_incidents --gen2 --region us-central1 --limit 50

# Check pipeline runs for errors
bq query --use_legacy_sql=false '
SELECT Status, ErrorCode, Message, DurationSeconds
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE PipelineName = "PagerDutyIncidentData"
ORDER BY RunTime DESC
LIMIT 5
'
```

---

## 📚 Full Documentation

- **Architecture**: `PAGERDUTY_PIPELINE_SUMMARY.md` (this folder)
- **Detailed Setup**: `CloudFunctions/pccw-internal-virt-agent-uat/pagerduty_incident_data/DEPLOYMENT.md`
- **Code Docs**: `CloudFunctions/pccw-internal-virt-agent-uat/pagerduty_incident_data/README.md`
- **CSV Consolidation**: `consolidate_insights.py` (for reference)

---

## 🔄 Sync Modes Quick Reference

### Full Pull (All Incidents)
```bash
curl -X POST "${CF_URL}?full_pull=true"
```
Use for: Initial load, recovery, full refresh  
Duration: 3-5 minutes

### Delta Pull (Last 3 hours)
```bash
curl -X POST "${CF_URL}?full_pull=false&hours_back=3"
```
Use for: Hourly scheduled runs (default)  
Duration: <1 minute

### Custom Lookback
```bash
curl -X POST "${CF_URL}?full_pull=false&hours_back=24"
```

---

## 📊 What You Can Now Do

✅ Query all incident history  
✅ Analyze by escalation policy  
✅ Calculate MTTA/MTTR metrics  
✅ Track service reliability  
✅ Monitor responder workload  
✅ Build dashboards  
✅ Create alerts  
✅ Audit incident response  

---

**Set a reminder to monitor the first few hourly runs!**  
The function logs to `GSO.PipelineRuns` so you can see success/failure.

Questions? See the detailed docs in this folder.
