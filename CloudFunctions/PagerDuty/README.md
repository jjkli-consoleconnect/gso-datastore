# PagerDuty to BigQuery Data Pipeline

Complete data sync pipeline from PagerDuty to Google BigQuery, featuring:

- **Incidents**: All incident data with status, assignments, escalation info
- **On-Call Schedules**: Current and historical on-call assignments
- **Services**: All services with escalation policy mappings
- **Escalation Policies**: Policy rules and rotation logic

## Architecture

- **Hourly Sync** (`Hourly/pagerduty/`): Local script for hourly syncs, logs to PipelineRuns table
- **Cloud Function** (`CloudFunctions/PagerDuty/`): Serverless deployment on GCP
- **Staging Pattern**: Uses temporary tables + MERGE for idempotent updates
- **Error Logging**: All runs logged to GSO.PipelineRuns table

## Setup

### 1. Store PagerDuty API Token

```bash
# Option A: Local (for testing)
cd Hourly/pagerduty
cat > pagerduty_config.json << EOF
{
  "pagerduty_api_token": "YOUR_TOKEN_HERE"
}
EOF

# Option B: Google Secret Manager (for production)
gcloud secrets create pagerduty-api-token \
  --replication-policy="automatic" \
  --data-file=- << EOF
YOUR_TOKEN_HERE
EOF
```

### 2. Create BigQuery Tables

```bash
cd Hourly/pagerduty
python create_tables.py
```

Tables created:
- `GSO.PagerDuty_Incidents` (partitioned by sync_time)
- `GSO.PagerDuty_Oncalls` (partitioned by sync_time)
- `GSO.PagerDuty_Services` (partitioned by sync_time)
- `GSO.PagerDuty_Escalation_Policies` (partitioned by sync_time)

### 3. Test Locally

```bash
cd Hourly/pagerduty
export PAGERDUTY_TOKEN="YOUR_TOKEN"
python main.py
```

### 4. Deploy to Cloud Function

```bash
cd CloudFunctions/PagerDuty
bash deploy.sh
```

Or manually:
```bash
gcloud functions deploy pagerduty-sync \
  --runtime python312 \
  --region europe-west2 \
  --project pccw-internal-virt-agent-uat \
  --trigger-http \
  --entry-point pagerduty_sync
```

## Schema

### PagerDuty_Incidents
| Column | Type | Notes |
|--------|------|-------|
| incident_id | STRING (PK) | Unique incident ID |
| incident_number | INTEGER | Human-readable incident number |
| title | STRING | Incident title |
| status | STRING | triggered, acknowledged, resolved |
| urgency | STRING | high, low |
| created_at | TIMESTAMP | When incident was created |
| service_id | STRING | FK to Services |
| assignee_names | STRING | Comma-separated assignee names |
| escalation_count | INTEGER | Number of escalations |
| sync_time | TIMESTAMP | When row was synced |

### PagerDuty_Oncalls
| Column | Type | Notes |
|--------|------|-------|
| on_call_id | STRING (PK) | schedule_id + user_id + start |
| user_id | STRING | PagerDuty user ID |
| user_email | STRING | User email |
| schedule_id | STRING | On-call schedule ID |
| escalation_level | INTEGER | Level in escalation policy |
| start | TIMESTAMP | When on-call period starts |
| end | TIMESTAMP | When on-call period ends |
| sync_time | TIMESTAMP | When row was synced |

### PagerDuty_Services
| Column | Type | Notes |
|--------|------|-------|
| service_id | STRING (PK) | Unique service ID |
| service_name | STRING | Service name |
| status | STRING | active, warning, critical |
| escalation_policy_id | STRING | FK to Escalation_Policies |
| teams_json | STRING | JSON array of team IDs |
| sync_time | TIMESTAMP | When row was synced |

### PagerDuty_Escalation_Policies
| Column | Type | Notes |
|--------|------|-------|
| policy_id | STRING (PK) | Unique policy ID |
| policy_name | STRING | Policy name |
| num_escalation_rules | INTEGER | Number of escalation rules |
| repeat_enabled | BOOLEAN | Whether policy repeats |
| escalation_rules_json | STRING | JSON rules array |
| sync_time | TIMESTAMP | When row was synced |

## Running Hourly via Scheduler

Add to Cloud Scheduler:

```bash
gcloud scheduler jobs create http pagerduty-sync \
  --schedule="0 * * * *" \
  --time-zone=UTC \
  --http-method=GET \
  --uri=https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/pagerduty-sync \
  --oidc-service-account-email=cloud-functions-sa@pccw-internal-virt-agent-uat.iam.gserviceaccount.com \
  --oidc-token-audience=https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/pagerduty-sync
```

## Monitoring

Check pipeline run logs:

```sql
SELECT 
  RunTime,
  Status,
  Message,
  RowsMerged,
  DurationSeconds,
  ErrorCode
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE PipelineName = 'pagerduty'
ORDER BY RunTime DESC
LIMIT 10
```

## Troubleshooting

### Authentication Errors
- Verify PagerDuty token is valid: `curl -H "Authorization: Token REDACTED" https://api.pagerduty.com/users/me`
- Check token has read permissions for incidents, on-calls, services, escalation policies

### Table Not Found
- Ensure tables are created: `python create_tables.py`
- Verify dataset exists: `GSO`

### Slow Syncs
- PagerDuty API is paginated (100 items per request)
- Set `LOG_LEVEL=DEBUG` to see pagination details
- Monitor `DurationSeconds` in PipelineRuns table

### No Data in Tables
- Check filter dates in API requests (currently fetches all recent data)
- Verify PagerDuty account has incidents/services/schedules
