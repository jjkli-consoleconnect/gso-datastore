# BQ HDWL Pipeline - Implementation Summary

## Created Files

### 1. `cloud_function_bq_hdwl/main.py`
Main Cloud Function that processes BigQuery HDWL emails.

**Key Features:**
- Receives Pub/Sub messages from `gmail-to-bq-hdwl` topic
- Downloads CSV attachments from Gmail using OAuth
- Robust CSV parsing with:
  - Multiple encoding support (UTF-8, UTF-16, Latin-1, CP1252)
  - Multiple delimiter support (comma, semicolon, tab)
  - Field standardization and mapping
- BigQuery operations:
  - Loads CSV data as NDJSON to staging tables
  - Executes MERGE queries to update target tables
  - Supports both HelpDeskAllNOC and WorkLog data
- Gmail label management:
  - Removes "pubsub" label after processing
  - Adds "ArchivedReports" label
- Pipeline run logging to `GSO.PipelineRuns` table
- Comprehensive error handling and logging

**Configuration:**
- Supports 2 CSV types with separate configs:
  - HelpDeskAllNOC: 33 columns, incident tracking
  - WorkLog: 8 columns, work log tracking
- Automatic type conversion for:
  - Timestamps (9 fields for HelpDeskAllNOC, 2 for WorkLog)
  - Integers (4 fields for HelpDeskAllNOC)
- Field mapping for CSV header normalization

### 2. `cloud_function_bq_hdwl/requirements.txt`
Python dependencies for the processor function:
- `functions-framework`: Cloud Functions runtime
- `google-cloud-secret-manager`: OAuth credential retrieval
- `google-cloud-bigquery`: BigQuery operations
- `google-cloud-pubsub`: Pub/Sub message handling
- `google-auth` + `google-auth-oauthlib`: OAuth authentication
- `google-api-python-client`: Gmail API access

### 3. `cloud_function_gmail_checker_updated/main.py`
Updated Gmail checker function that monitors both:

**Pattern 1 (Existing):**
- Subject: `pubsub - Handover Queue`
- From: `noreply-bmchelix@onbmc.com`
- Publishes to: `gmail-handover-reports` topic

**Pattern 2 (New):**
- Subject: `pubsub - BQ - GSO.HDWL`
- From: `noreply-bmchelix@onbmc.com`
- Publishes to: `gmail-to-bq-hdwl` topic

**Functionality:**
- HTTP trigger (called by Cloud Scheduler every 1 minute)
- Searches Gmail for emails matching configured patterns
- Publishes message IDs and metadata to respective Pub/Sub topics
- Comprehensive error handling and logging

### 4. `cloud_function_gmail_checker_updated/requirements.txt`
Python dependencies (same as original, with added pubsub library)

### 5. `cloud_function_bq_hdwl/DEPLOYMENT.md`
Complete deployment guide with:
- Prerequisites and setup requirements
- Step-by-step deployment instructions
- Processing flow diagram
- CSV format specifications
- Error handling and troubleshooting
- Rollback procedures
- Command reference

## Deployment Instructions

### Prerequisites
✅ Already completed:
- Gmail OAuth token in Secret Manager (`gmail-oauth-token` v2)
- Pub/Sub topic created: `gmail-to-bq-hdwl`
- BigQuery datasets and tables ready
- Cloud Scheduler job running every 1 minute

### Deploy Process
Run the following commands:

```bash
# 1. Deploy new processor function
gcloud functions deploy process-bq-hdwl-email \
  --gen2 \
  --runtime python311 \
  --region europe-west2 \
  --source cloud_function_bq_hdwl \
  --entry-point process_bq_hdwl_email \
  --trigger-topic gmail-to-bq-hdwl \
  --project pccw-internal-virt-agent-uat

# 2. Update checker function
gcloud functions deploy gmail-checker-oauth \
  --gen2 \
  --runtime python311 \
  --region europe-west2 \
  --source cloud_function_gmail_checker_updated \
  --entry-point gmail_checker_oauth \
  --trigger-http \
  --allow-unauthenticated \
  --project pccw-internal-virt-agent-uat
```

## Data Flow

```
1. Email Arrives in Gmail
   ↓
2. Cloud Scheduler (every 1 min) triggers gmail-checker-oauth
   ↓
3. gmail-checker-oauth searches for matching emails
   ├─ Subject: "pubsub - BQ - GSO.HDWL"
   ├─ From: "noreply-bmchelix@onbmc.com"
   └─ Label: "pubsub"
   ↓
4. Publishes message to Pub/Sub topic: gmail-to-bq-hdwl
   ↓
5. process-bq-hdwl-email function triggered
   ↓
6. Downloads attachments from Gmail
   ↓
7. Parses CSV files (robust multi-encoding parser)
   ↓
8. Loads to BigQuery staging tables
   ├─ Staging.HelpDeskAllNOC (if helpdesk_*.csv found)
   └─ Staging.WorkLogAllNOC (if worklog_*.csv found)
   ↓
9. Executes MERGE query to target tables
   ├─ GSO.HelpDeskAllNOC (primary key: Incident_Number)
   └─ GSO.WorkLogAllNOC (primary key: WorkLog_ID)
   ↓
10. Manages Gmail labels
    ├─ Removes: "pubsub"
    └─ Adds: "ArchivedReports"
    ↓
11. Logs pipeline run to GSO.PipelineRuns
    ├─ RunTime, PipelineName, RunID, Status, Message, RowsMerged
```

## Testing Plan

1. **Send Test Email:**
   - Recipient: your Gmail account (with OAuth token)
   - Subject: `pubsub - BQ - GSO.HDWL`
   - From: `noreply-bmchelix@onbmc.com` (can use a Gmail alias or test account)
   - Label: Apply the "pubsub" label in Gmail
   - Attachments: `helpdesk_test.csv` and/or `worklog_test.csv`

2. **Monitor Execution:**
   ```bash
   # Watch function logs in real-time
   gcloud functions logs read process-bq-hdwl-email \
     --gen2 --region europe-west2 \
     --project pccw-internal-virt-agent-uat --limit 50 --follow
   ```

3. **Verify BigQuery:**
   ```sql
   -- Check staging tables
   SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.Staging.HelpDeskAllNOC`;
   SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.Staging.WorkLogAllNOC`;
   
   -- Check target tables
   SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`;
   SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC`;
   
   -- Check pipeline runs
   SELECT * FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
   WHERE PipelineName = 'GmailToBQ - HDWL'
   ORDER BY RunTime DESC
   LIMIT 10;
   ```

4. **Verify Labels:**
   - Check that email in Gmail has "ArchivedReports" label
   - Check that "pubsub" label has been removed

## Key Features

### Robust CSV Parsing
- ✅ Multi-encoding support (UTF-8, UTF-16, Latin-1, CP1252)
- ✅ Multi-delimiter support (comma, semicolon, tab)
- ✅ BOM handling (removes UTF-8 BOM if present)
- ✅ Field mapping with standardization
- ✅ Type conversion for timestamps and integers

### BigQuery Integration
- ✅ MERGE queries for updates (existing records) + inserts (new records)
- ✅ Primary key based matching
- ✅ Staging to target pipeline
- ✅ Centralized pipeline run logging

### Gmail Integration
- ✅ OAuth-based authentication (no domain-wide delegation needed)
- ✅ Message search with multiple criteria
- ✅ Label management (remove/add)
- ✅ Attachment retrieval

### Error Handling
- ✅ Comprehensive try-catch blocks
- ✅ Structured logging with context
- ✅ Pipeline run logging with status and error messages
- ✅ Graceful handling of missing data

## Configuration Reference

### Email Monitoring
```python
EMAIL_PATTERNS = [
    {
        "subject": "pubsub - BQ - GSO.HDWL",
        "from": "noreply-bmchelix@onbmc.com",
        "label": "pubsub",
        "pubsub_topic": "gmail-to-bq-hdwl"
    }
]
```

### CSV Type: HelpDeskAllNOC
```python
{
    "filename_prefix": "helpdesk",
    "staging_dataset": "Staging",
    "staging_table": "HelpDeskAllNOC",
    "target_dataset": "GSO",
    "target_table": "HelpDeskAllNOC",
    "primary_key": "Incident_Number",
    "timestamp_fields": ["GCSC_1st_Customer_Update", "Closed_Date", "Submit_Date", ...],
    "integer_fields": ["Initial_Response_Time", "Second_Response_Time", ...]
}
```

### CSV Type: WorkLog
```python
{
    "filename_prefix": "worklog",
    "staging_dataset": "Staging",
    "staging_table": "WorkLogAllNOC",
    "target_dataset": "GSO",
    "target_table": "WorkLogAllNOC",
    "primary_key": "WorkLog_ID",
    "timestamp_fields": ["WorkLog_Submit_Date", "Last_Modified_Date"],
    "integer_fields": []
}
```

## Next Actions

- [ ] Deploy `process-bq-hdwl-email` Cloud Function
- [ ] Deploy updated `gmail-checker-oauth` Cloud Function
- [ ] Test with sample CSV files
- [ ] Verify BigQuery data loading
- [ ] Confirm label management working
- [ ] Monitor first production run
- [ ] Set up alerts in Cloud Monitoring (optional)

## Support & Maintenance

**For future modifications:**
1. Update CSV configuration in `EMAIL_PATTERNS` for new patterns
2. Add new table mappings to `CSV_CONFIGURATIONS`
3. Modify field mapping in `field_map` dictionary
4. Update timestamp/integer field lists as needed
5. Redeploy functions after changes

**Log Location:**
- Cloud Logging console: `Cloud Functions > process-bq-hdwl-email > Logs`
- BigQuery logging: `GSO.PipelineRuns` table

**Common Tasks:**
- View logs: `gcloud functions logs read process-bq-hdwl-email --gen2 --region europe-west2 --project pccw-internal-virt-agent-uat`
- Update function: Re-run deploy command with modified source code
- Check scheduler: `gcloud scheduler jobs describe gmail-check-job --location europe-west2 --project pccw-internal-virt-agent-uat`
