# PagerDuty Incidents Sync Cloud Function

Comprehensive incident data pipeline that syncs **all available incident information** from PagerDuty to BigQuery with intelligence for dashboard visualization and SLA tracking.

## Overview

This Cloud Function is a **dedicated incidents pipeline** separate from the admin database sync. It focuses on fetching complete incident data including resolution timestamps, assignments, and audit trails for analytics and dashboard purposes.

## Architecture

### Strategy: Intelligent Hybrid Approach

1. **Phase 1 - List Fetch** (Efficient)
   - Fetch incidents list using delta sync (3-hour window by default)
   - Or full sync for complete history
   - Filter by status (triggered, acknowledged, resolved)

2. **Phase 2 - Parallel Detail Enrichment** (Smart)
   - Fetch full incident details for each incident in parallel
   - Includes all resolution timestamps and metadata
   - Concurrent calls with rate limiting (5 workers)

3. **Phase 3 - Optional Log Entries** (Audit Trail)
   - Fetch complete log entries for resolved incidents only
   - Provides full audit trail of incident lifecycle
   - Can be disabled to save API quota

4. **Phase 4 - BigQuery Merge** (Upsert)
   - Use MERGE operation for efficient upserts
   - Time-partitioned by SyncTime
   - Clustered by status, ServiceId, created_at for fast queries

## Data Model

### Fields Captured

**Core Incident Fields:**
- `id`, `incident_number`, `title`, `description`
- `status` (triggered, acknowledged, resolved)
- `urgency` (low, high)
- `incident_key`, `assigned_via`

**Resolution Data (Critical for Dashboards):**
- `created_at` - When incident triggered
- `first_resolved_at` - First time incident was resolved
- `last_resolved_at` - Most recent resolution time
- `resolved_at` - Current resolution timestamp

**Assignment & Escalation:**
- `AssignmentSummaries` (REPEATED) - User + timestamp pairs
- `AcknowledgementSummaries` (REPEATED) - Acknowledger + timestamp
- `EscalationPolicyId`, `EscalationPolicySummary`

**Service & Organization:**
- `ServiceId`, `ServiceSummary`
- `TeamSummaries` (REPEATED)
- `PriorityName`, `PriorityId`
- `IncidentTypeName`, `IncidentTypeId`

**Conference & Collaboration:**
- `ConferenceBridgeConferenceNumber`
- `ConferenceBridgeConferenceURL`

**Audit Trail (When log_entries enabled):**
- `TotalLogEntries` - Count of lifecycle events
- `FirstResolutionEvent` - When first resolved
- `LastResolutionEvent` - When last resolved

## Configuration

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `delta` | `true` | Use 3-hour delta sync (`true`) or full sync (`false`) |
| `fetch_log_entries` | `false` | Include incident log entries/audit trail |
| `statuses` | `triggered,acknowledged,resolved` | Comma-separated status filters |

### Environment

- **GCP Project**: `pccw-internal-virt-agent-uat`
- **BigQuery Dataset**: `GSO`
- **BigQuery Table**: `PagerDutyIncidents`
- **Secret**: `pagerduty-api-token` (stored in Secret Manager)

## Usage Examples

### Delta Sync (3 hours, Basic)
```
GET /sync_incidents?delta=true&fetch_log_entries=false
```
**Use Case**: Regular scheduled runs, efficient quota usage
**Result**: ~400 incident details fetched

### Full Sync with Audit Trail
```
GET /sync_incidents?delta=false&fetch_log_entries=true
```
**Use Case**: Initial load or periodic full audit
**Result**: All incidents + complete log entries

### Resolved Incidents Only, No Log Entries
```
GET /sync_incidents?delta=true&statuses=resolved&fetch_log_entries=false
```
**Use Case**: Focus on closed/resolved incidents
**Result**: Only resolved incidents with resolution data

### Historical Load (Full Sync, No Logs)
```
GET /sync_incidents?delta=false&fetch_log_entries=false
```
**Use Case**: Initial backfill
**Result**: Complete incident history

## Performance Characteristics

### API Calls Estimation

**Per Delta Sync Run (3-hour window):**
- 1 call to `/incidents` list → ~400 incidents
- 400 calls to `/incidents/{id}` detail (parallel, 5 workers)
- Optional: 400 calls to `/incidents/{id}/log_entries` (if enabled)

**Total**: ~401 calls (no logs) or ~801 calls (with logs)
**Time**: ~60-90 seconds with parallelization

### BigQuery Operations

**Per Run:**
- 1 MERGE query combining staging → main table
- Automatic partitioning by SyncTime
- Clustered queries on status, ServiceId, created_at

**Efficiency:**
- Only updates changed records (MERGE ON id)
- Automatic time partitioning for cost optimization
- Clustering accelerates common dashboard queries

## BigQuery Schema

```sql
-- Core incident info
id (STRING, REQUIRED)
incident_number (INTEGER)
title (STRING)
description (STRING)
status (STRING) - CLUSTERED

-- Timing (KEY FOR DASHBOARDS)
created_at (TIMESTAMP)
first_resolved_at (TIMESTAMP) ← First resolution
last_resolved_at (TIMESTAMP) ← Latest resolution
resolved_at (TIMESTAMP)
SyncTime (TIMESTAMP) - PARTITIONED

-- Relationships
ServiceId (STRING) - CLUSTERED
ServiceSummary (STRING)
EscalationPolicyId (STRING)
TeamSummaries (REPEATED)
AssignmentSummaries (REPEATED)
AcknowledgementSummaries (REPEATED)

-- Audit Trail (if log_entries enabled)
TotalLogEntries (INTEGER)
FirstResolutionEvent (TIMESTAMP)
LastResolutionEvent (TIMESTAMP)
```

## Sample Queries for Dashboards

### SLA Metrics
```sql
SELECT
  status,
  COUNT(*) as incident_count,
  AVG(TIMESTAMP_DIFF(resolved_at, created_at, MINUTE)) as avg_resolution_minutes,
  MIN(TIMESTAMP_DIFF(resolved_at, created_at, MINUTE)) as min_resolution_minutes,
  MAX(TIMESTAMP_DIFF(resolved_at, created_at, MINUTE)) as max_resolution_minutes
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`
WHERE resolved_at IS NOT NULL
  AND DATE(SyncTime) = CURRENT_DATE()
GROUP BY status
```

### Service Performance
```sql
SELECT
  ServiceSummary,
  COUNT(*) as total_incidents,
  COUNTIF(status = 'resolved') as resolved_count,
  AVG(TIMESTAMP_DIFF(resolved_at, created_at, HOUR)) as avg_hours_to_resolve
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`
WHERE DATE(SyncTime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY ServiceSummary
ORDER BY total_incidents DESC
```

### Assignment Workload
```sql
SELECT
  REGEXP_EXTRACT(assignment, r'^([^ -]+)') as assigned_user,
  COUNT(*) as incident_count
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidents`,
  UNNEST(AssignmentSummaries) as assignment
WHERE DATE(SyncTime) = CURRENT_DATE()
GROUP BY assigned_user
ORDER BY incident_count DESC
```

## Deployment

### Deploy to Cloud Functions

```bash
gcloud functions deploy sync_incidents \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --source ./CloudFunctions/pagerduty_incidents \
  --entry-point sync_incidents \
  --memory 512MB \
  --timeout 540 \
  --region europe-west2
```

### Schedule with Cloud Scheduler

**For Delta Sync (Every 3 hours):**
```bash
gcloud scheduler jobs create http sync-incidents-delta \
  --schedule="0 */3 * * *" \
  --uri="https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_incidents?delta=true&fetch_log_entries=false" \
  --http-method=GET \
  --location=europe-west2
```

**For Full Sync (Weekly):**
```bash
gcloud scheduler jobs create http sync-incidents-full \
  --schedule="0 2 * * 0" \
  --uri="https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/sync_incidents?delta=false&fetch_log_entries=false" \
  --http-method=GET \
  --location=europe-west2
```

## Intelligent Features

### 1. Parallel Enrichment
- Fetches detail endpoints concurrently (5 workers)
- Reduces time from ~400s sequential to ~80s parallel
- Respects rate limits without explicit throttling

### 2. Log Entries Optional
- Disabled by default to save API quota
- Enable only when audit trail needed
- Provides complete incident lifecycle in separate queries

### 3. Status Filtering
- Default: All statuses (triggered, acknowledged, resolved)
- Can filter to specific statuses via query param
- Reduces BigQuery storage if focusing on resolved only

### 4. Time-Partitioned Storage
- Automatic partition by SyncTime
- BigQuery automatically prunes old partitions
- Queries faster and cheaper when filtered by date

### 5. Upsert with MERGE
- Only updates changed records
- Idempotent operation (safe to retry)
- Staging table approach is GCS-efficient

### 6. Clustering Strategy
- `status` - Most common filter
- `ServiceId` - Common dashboard dimension
- `created_at` - Time-range queries
- Accelerates all major dashboard patterns

## Cost Optimization

### Recommended Setup

**Hourly delta sync (basic):**
- 400 incidents/hour × 3 = 1,200 incidents scanned
- Minimal log entries storage
- Estimated: $5-10/month

**3-hour delta sync (recommended):**
- 400 incidents × 8 = 3,200 incidents/day
- Balanced efficiency/freshness
- Estimated: $3-5/month

**Weekly full sync + daily delta:**
- Full on Sunday: all incidents
- Delta M-S: 3,200 incidents
- Estimated: $5-8/month

## Troubleshooting

### Incidents have NULL resolution timestamps
✓ **Solution**: They likely haven't been resolved yet. Filter on `status = 'resolved'`

### API rate limiting
**Solution**: Reduce concurrent workers, increase `delta` window, or disable `fetch_log_entries`

### BigQuery quota exceeded
**Solution**: Reduce sync frequency, filter to specific statuses, disable log entries

## Future Enhancements

1. **Incident Relationships**: Fetch merged incidents, related incidents
2. **Alert Grouping**: Track alert grouping settings and performance
3. **Escalation Metrics**: Deep analysis of escalation patterns
4. **Incident Responses**: Track who responded and when (slack integration)
5. **Custom Fields**: Sync and track incident custom fields
6. **Webhook Integration**: Real-time updates via webhooks instead of polling

---

**Version**: 1.0  
**Last Updated**: February 2026  
**Author**: Data Engineering Team
