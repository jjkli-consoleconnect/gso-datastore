# PagerDuty Incidents Sync - Deployment Guide

## Quick Start

### Step 1: Verify File Structure

```
CloudFunctions/pagerduty_incidents/
├── main.py                  # Main Cloud Function
├── requirements.txt         # Python dependencies
└── README.md               # Documentation (you're reading this)
```

### Step 2: Deploy to Cloud Functions

```bash
cd g:/My\ Drive/Scripts

# Deploy the incident sync function
gcloud functions deploy sync_incidents \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --source ./CloudFunctions/pagerduty_incidents \
  --entry-point sync_incidents \
  --memory 512MB \
  --timeout 540 \
  --region europe-west2 \
  --set-env-vars GCP_PROJECT=pccw-internal-virt-agent-uat
```

### Step 3: Test the Function

#### Test Delta Sync (3-hour window)
```bash
gcloud functions call sync_incidents \
  --region=europe-west2 \
  --data='{"queryStringParameters": {"delta": "true", "fetch_log_entries": "false"}}'
```

#### Or via HTTP
```bash
curl "https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_incidents?delta=true&fetch_log_entries=false"
```

### Step 4: Schedule Recurring Sync

#### Create Delta Sync Job (Every 3 hours)
```bash
gcloud scheduler jobs create http sync-incidents-delta \
  --schedule="0 */3 * * *" \
  --uri="https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_incidents?delta=true&fetch_log_entries=false" \
  --http-method=GET \
  --location=europe-west2 \
  --oidc-service-account-email=cloud-scheduler@pccw-internal-virt-agent-uat.iam.gserviceaccount.com
```

#### Create Full Sync Job (Weekly, Sunday 2am)
```bash
gcloud scheduler jobs create http sync-incidents-full \
  --schedule="0 2 * * 0" \
  --uri="https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_incidents?delta=false&fetch_log_entries=false" \
  --http-method=GET \
  --location=europe-west2 \
  --oidc-service-account-email=cloud-scheduler@pccw-internal-virt-agent-uat.iam.gserviceaccount.com
```

## Verification

### Check BigQuery Table Creation

```sql
-- Should return table details
SELECT
  table_name,
  row_count,
  size_bytes,
  creation_time
FROM `pccw-internal-virt-agent-uat.GSO.__TABLES__`
WHERE table_name = 'PagerDutyIncidents'
```

### Verify Data Loaded

```sql
-- Check latest incidents
SELECT
  incident_number,
  title,
  status,
  created_at,
  resolved_at,
  first_resolved_at,
  last_resolved_at,
  SyncTime
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`
ORDER BY SyncTime DESC
LIMIT 10
```

### Check Resolution Data

```sql
-- Verify resolution timestamps populated
SELECT
  COUNT(*) as total_incidents,
  COUNTIF(resolved_at IS NOT NULL) as with_resolution_time,
  COUNTIF(first_resolved_at IS NOT NULL) as with_first_resolved,
  COUNTIF(last_resolved_at IS NOT NULL) as with_last_resolved
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`
WHERE DATE(SyncTime) = CURRENT_DATE()
```

## Configuration Options

### Default Behavior
- **Delta Sync**: 3 hours
- **Statuses**: All (triggered, acknowledged, resolved)
- **Log Entries**: Disabled

### Query Parameter Examples

| Goal | URL Parameter |
|------|-------|
| Full sync with audit trail | `?delta=false&fetch_log_entries=true` |
| Resolved incidents only | `?statuses=resolved` |
| All triggered incidents | `?statuses=triggered` |
| Multiple statuses | `?statuses=triggered,resolved` |

## Cost Analysis

### Per Run (Delta Sync)
| Component | Cost |
|-----------|------|
| 1x list endpoint call | ~$0.0001 |
| 400x detail endpoint calls | ~$0.0004 |
| BigQuery MERGE query | ~$0.002 |
| Cloud Function execution | ~$0.0005 |
| **Total per run** | **~$0.003** |

### Monthly (8 runs/day × 30 days)
- **240 runs × $0.003** = **$0.72/month**
- Plus BigQuery storage: ~$2-5/month
- **Total: ~$3-6/month**

### With Log Entries (Weekly full sync only)
- **30 × $0.006** = **$0.18/week**
- **~$0.72/month**
- **Total with log entries: ~$4-7/month**

## Monitoring

### Cloud Function Logs
```bash
# View function logs
gcloud functions logs read sync_incidents \
  --region=europe-west2 \
  --limit 50 \
  --format=json
```

### Check Pipeline Run Logs
```sql
SELECT
  pipeline_name,
  status,
  run_time,
  records_processed,
  records_inserted,
  sync_type
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE pipeline_name = 'PagerDuty Incidents Sync'
ORDER BY run_time DESC
LIMIT 20
```

## Troubleshooting

### Function Returns 500 Error

**Check logs:**
```bash
gcloud functions logs read sync_incidents --region=europe-west2
```

**Common issues:**
1. **API token not found**: Verify secret in Secret Manager
2. **BigQuery permissions**: Ensure service account has `roles/bigquery.dataEditor`
3. **Network connectivity**: Check firewall rules allow API calls

### No Data Inserted

**Check:**
```sql
SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`
```

**If 0 rows:**
1. Verify incidents exist in PagerDuty
2. Check API token has correct scopes
3. Look for API errors in Cloud Function logs

### Resolution Timestamps are NULL

**This is expected if:**
- Incidents haven't been resolved yet (status = "triggered" or "acknowledged")
- Use query: `WHERE status = 'resolved'`

**If they should have data:**
1. Verify detail endpoint is being called
2. Check PagerDuty API has that data
3. Ensure log_entries weren't truncated

## Next Steps

### 1. Create BigQuery Dashboards
Use the sample queries in README.md to create Data Studio dashboards

### 2. Set Up Alerting
Create Cloud Monitoring alerts for sync failures

### 3. Archive Old Data
Set up BigQuery dataset expiration to manage storage costs

### 4. Enable Audit Trail
Once comfortable, enable log_entries for complete audit history

## Contact & Support

For issues or improvements, check:
1. BigQuery query results directly
2. Cloud Function logs
3. PagerDuty API documentation
4. GCP documentation

---

**Deployment Date**: [Your date]  
**Deployed By**: [Your name]  
**Status**: Active
