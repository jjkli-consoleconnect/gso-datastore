# PagerDuty Incident Data Consolidation Pipeline

A comprehensive Cloud Function-based pipeline that consolidates incident data from PagerDuty Insights exports and the PagerDuty API, loading enriched data into BigQuery.

## Overview

This pipeline:
- **Consolidates** data from 3 PagerDuty Insights exports (incident activity, responder metrics, service performance)
- **Pulls live data** from PagerDuty API (incidents, services, users, escalation policies)
- **Enriches** incident data with service and user metadata
- **Stages** data to a temporary BigQuery table
- **Merges** using incident number as the unique key
- **Implements** clustering by escalation policy and resolved date for optimal query performance

## Data Flow

```
PagerDuty API          PagerDuty Insights Exports
    ↓                          ↓
 /incidents              incident_activity.csv
 /services               responder_export.csv
 /users                  service_performance_export.csv
 /log_entries                 ↓
    ↓                       (Initial consolidation)
    └──────────────────────┬──────────────────────┘
                           ↓
                 Enrich with metadata
                 Map incident numbers
                           ↓
                 Temp table in BQ
                  (with sync_time)
                           ↓
                  MERGE by incident_number
                           ↓
         GSO.PagerDutyIncidentData
   (Clustered by escalation_policy,
  resolved_at, created_at)
```

## BigQuery Schema

### Target Table: `GSO.PagerDutyIncidentData`

| Field | Type | Clustering | Description |
|-------|------|-----------|-------------|
| incident_id | STRING | - | PagerDuty internal incident ID |
| **incident_number** | STRING | **Key** | Unique incident number (merge key) |
| title | STRING | - | Incident title |
| description | STRING | - | Incident description |
| created_at | TIMESTAMP | Partition | Incident creation time |
| status | STRING | - | triggered, acknowledged, resolved |
| urgency | STRING | - | low, high |
| incident_key | STRING | - | Deduplication key |
| service_id | STRING | - | Associated service ID |
| service_name | STRING | - | Associated service name |
| escalation_policy_id | STRING | - | Escalation policy ID |
| **escalation_policy_name** | STRING | **Cluster** | Escalation policy name |
| assignees_json | STRING | - | JSON array of assignee names |
| first_trigger_time | TIMESTAMP | - | First trigger log entry time |
| acknowledgement_time | TIMESTAMP | - | When incident was acknowledged |
| **resolved_at** | TIMESTAMP | **Cluster** | Resolution time |
| last_status_update_at | TIMESTAMP | - | Last status update |
| time_to_resolve_seconds | INTEGER | - | TTR in seconds (calculated) |
| html_url | STRING | - | Link to PagerDuty UI |
| sync_time | TIMESTAMP | - | When data was synced |

### Clustering Strategy
- **Primary**: `escalation_policy_name` (for team-based filtering and RBAC)
- **Secondary**: `resolved_at` (for date-based analysis and cost optimization)
- **Tertiary**: `created_at` (for temporal windowing)

### Partitioning
- **Type**: DAY
- **Field**: `created_at`
- **Benefit**: Automatic pruning for date-range queries

## Cloud Function Configuration

### Deployment

```bash
gcloud functions deploy sync_pagerduty_incidents \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point sync_pagerduty_incidents \
  --memory 512MB \
  --timeout 540s \
  --set-env-vars GOOGLE_CLOUD_PROJECT=pccw-internal-virt-agent-uat
```

### HTTP Request Parameters

#### Full Pull (Initial Load)
```
GET /sync_pagerduty_incidents?full_pull=true
```

#### Delta Pull (Incremental - Default)
```
GET /sync_pagerduty_incidents?full_pull=false&hours_back=3
```

#### Custom Statuses
```
GET /sync_pagerduty_incidents?full_pull=true&statuses=triggered,acknowledged,resolved
```

### Query Parameters

| Parameter | Default | Example | Description |
|-----------|---------|---------|-------------|
| `full_pull` | false | true | Fetch all incidents or just recent ones |
| `hours_back` | 3 | 24 | Hours back to fetch when delta |
| `statuses` | triggered,acknowledged,resolved | resolved,acknowledged | Comma-separated incident statuses |

## Scheduling & Automation

### Initial Full Pull (One-time)
```bash
curl -X POST https://region-project.cloudfunctions.net/sync_pagerduty_incidents?full_pull=true
```

### Hourly Delta Pulls (Cloud Scheduler)

Create a Cloud Scheduler job:
```bash
gcloud scheduler jobs create http pd-incidents-hourly \
  --schedule="0 * * * *" \
  --uri="https://region-project.cloudfunctions.net/sync_pagerduty_incidents" \
  --http-method=GET \
  --tz="UTC" \
  --message-body=""
```

**Note**: The function defaults to `full_pull=false` with `hours_back=3`, so it automatically does incremental syncs every hour.

## Authentication & Secrets

### Required Secret: `pagerduty-api-token`

1. Create the secret in Google Cloud Secret Manager:
```bash
echo -n "YOUR_PAGERDUTY_API_TOKEN" | gcloud secrets create pagerduty-api-token --data-file=-
```

2. Grant the Cloud Function service account access:
```bash
gcloud secrets add-iam-policy-binding pagerduty-api-token \
  --member=serviceAccount:PROJECT_ID@appspot.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

## Response Format

### Success (200)
```json
{
  "status": "success",
  "incidents_synced": 45,
  "sync_type": "delta",
  "timestamp": "2026-02-06T15:30:00.000000+00:00",
  "duration_seconds": 23.5,
  "rows_merged": 45
}
```

### Error (500)
```json
{
  "error": "Failed to fetch incidents from PagerDuty API"
}
```

## Monitoring & Logging

### Pipeline Run Logging

All runs are logged to `GSO.PipelineRuns` with:
- `PipelineName`: "PagerDutyIncidentData"
- `RunID`: Unique UUID per execution
- `Status`: SUCCESS | FAILED
- `ErrorCode`: Specific error type if failed
- `RowsMerged`: Number of records updated/inserted
- `DurationSeconds`: Execution time
- `Message`: Detailed log message

### Query Recent Runs
```sql
SELECT 
  RunTime,
  Status,
  RowsMerged,
  DurationSeconds,
  Message
FROM GSO.PipelineRuns
WHERE PipelineName = "PagerDutyIncidentData"
ORDER BY RunTime DESC
LIMIT 10
```

## Analysis Examples

### MTTA/MTTR Analysis
The `time_to_resolve_seconds` field enables quick TTR calculations:

```sql
SELECT
  escalation_policy_name,
  service_name,
  COUNT(*) as incident_count,
  AVG(time_to_resolve_seconds) / 60 as avg_ttr_minutes,
  PERCENTILE_CONT(time_to_resolve_seconds, 0.5) OVER (PARTITION BY escalation_policy_name) / 60 as p50_ttr_minutes,
  PERCENTILE_CONT(time_to_resolve_seconds, 0.95) OVER (PARTITION BY escalation_policy_name) / 60 as p95_ttr_minutes
FROM GSO.PagerDutyIncidentData
WHERE resolved_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY escalation_policy_name, service_name
ORDER BY avg_ttr_minutes DESC
```

### Escalation Policy Performance
```sql
SELECT
  escalation_policy_name,
  COUNT(*) as total_incidents,
  COUNTIF(status = 'resolved') as resolved,
  COUNTIF(status = 'resolved') / COUNT(*) as resolution_rate,
  DATE(created_at) as incident_date
FROM GSO.PagerDutyIncidentData
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY escalation_policy_name, incident_date
ORDER BY incident_date DESC, total_incidents DESC
```

### Responder Assignment Patterns
```sql
SELECT
  REGEXP_EXTRACT_ALL(assignees_json, r'"([^"]+)"') as assignees,
  COUNT(*) as incident_count,
  service_name,
  escalation_policy_name
FROM GSO.PagerDutyIncidentData
WHERE resolved_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND assignees_json IS NOT NULL
GROUP BY assignees, service_name, escalation_policy_name
LIMIT 20
```

## Troubleshooting

### Issue: "Failed to retrieve PagerDuty API token"
**Solution**: 
1. Verify secret exists: `gcloud secrets list`
2. Verify service account has access: `gcloud secrets get-iam-policy pagerduty-api-token`
3. Check Cloud Function service account: `gcloud functions describe sync_pagerduty_incidents --format='value(serviceConfig.serviceAccountEmail)'`

### Issue: Slow delta pulls (should be <2 mins)
**Solution**: 
1. Check PagerDuty API rate limits in logs
2. Reduce `hours_back` parameter if too many incidents
3. Consider splitting into multiple endpoints (services, users separately)

### Issue: Data gaps in BigQuery
**Solution**:
1. Manually trigger full pull: `curl -X POST https://url?full_pull=true`
2. Check PipelineRuns table for failed executions
3. Verify escalation_policy_name clustering isn't causing issues

## Development & Testing

### Local Testing

```python
import json
from datetime import datetime, timezone

# Simulate a function request
class MockRequest:
    def __init__(self, args=None):
        self.args = args or {}
    
    def get(self, key, default=None):
        return self.args.get(key, default)

# Test with environment variables
os.environ['GOOGLE_CLOUD_PROJECT'] = 'pccw-internal-virt-agent-uat'
os.environ['PAGERDUTY_TOKEN'] = 'YOUR_TOKEN_HERE'

request = MockRequest({'full_pull': 'true'})
result = sync_pagerduty_incidents(request)
print(json.dumps(result, indent=2))
```

## Future Enhancements

- [ ] Support for incident custom fields from PagerDuty
- [ ] Integration with Insights metrics (MTTA, MTTR aggregates)
- [ ] Real-time incident update webhooks
- [ ] Automated alerts for SLA breaches
- [ ] Team-based RBAC for BigQuery views
- [ ] Historical trend analysis views
