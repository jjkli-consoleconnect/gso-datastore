# Verification Dispute → BigQuery Sync

Syncs Verification Dispute data from Google Sheets to BigQuery with intelligent date parsing and data validation.

## Features

- ✅ Intelligent date parsing (handles DD/MM/YYYY, DD-MM-YYYY, "1 Jan 2024", etc.)
- ✅ Data type validation for dates, numbers, and strings
- ✅ Currency symbol and comma removal for numeric fields
- ✅ **Simple WRITE_TRUNCATE** - Overwrites table each sync (perfect for small datasets)
- ✅ Automatic table creation with partitioning and clustering
- ✅ Partitioned by `file_dispute_date` for better performance
- ✅ Clustered by `file_dispute_date`, `vendor_name`, `dispute_category_reason`
- ✅ Detailed error logging
- ✅ Smart update trigger (syncs 15 minutes after last edit)

## Setup Instructions

### 1. Configure the Script

Open `Code.gs` and update these constants:

```javascript
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE'; // Your Google Sheet ID
const SHEET_NAME = 'Sheet1'; // Your sheet tab name
const TEMP_FOLDER_ID = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // Temp folder for JSON files
```

### 2. Enable BigQuery API

1. In the Apps Script editor, go to **Services** (+ icon)
2. Find and add **BigQuery API v2**
3. Verify it appears in `appsscript.json`

### 3. Grant Permissions

Run `importVerificationDisputeToBigQuery()` manually the first time:
1. Click the **Select function** dropdown
2. Choose `importVerificationDisputeToBigQuery`
3. Click **Run**
4. Grant the required permissions when prompted

### 4. Set Up Automatic Sync (Optional)

Choose one option:

**Option A: Smart Trigger (Recommended)**
- Syncs 15 minutes after last sheet edit
- Run once: `setupSmartUpdateTrigger()`

**Option B: Daily Trigger**
- Syncs every day at 2:00 AM
- Run once: `createDailyTrigger()`

## How It Works

### Table Creation (Automatic)
The script automatically creates the BigQuery table if it doesn't exist with:
- **Partitioning**: By `file_dispute_date` (DATE) for efficient date range queries
- **Clustering**: By `file_dispute_date`, `vendor_name`, `dispute_category_reason` for fast filtering
- **Schema**: All columns properly typed (DATE, NUMERIC, STRING, TIMESTAMP)

### Sync Strategy (WRITE_TRUNCATE)
Since dispute data is relatively small and relatively static:
- Table is completely overwritten on each sync
- No need for complex merge logic or duplicate handling
- Simpler, faster, and easier to understand
- Full refresh ensures data consistency

If you need incremental updates later, we can switch to MERGE logic.

## Data Mapping

| Google Sheet Header | BigQuery Column | Type |
|-------------------|----------------|------|
| File Dispute Date | file_dispute_date | DATE (partitioning & clustering key) |
| IS ID | is_id | STRING |
| Vendor Name | vendor_name | STRING (clustering key) |
| Charged Company | charged_company | STRING |
| Dispute Category/ Reason | dispute_category_reason | STRING (clustering key) |
| Invoice Number | invoice_number | STRING |
| Line # | line | NUMERIC |
| Dispute Amount in USD | dispute_amount_in_usd | NUMERIC |
| ... | ... | ... |

All column names are automatically sanitized to valid BigQuery field names.

## Date Format Validation

The script handles multiple date formats:
- ✅ `15/01/2024` (DD/MM/YYYY) - **Primary format**
- ✅ `15-01-2024` (DD-MM-YYYY)
- ✅ `1 Jan 2024` (Day Month Year)
- ✅ `2024-01-15` (ISO format)

Invalid dates are logged and set to NULL.

## Target Table

- **Project**: `pccw-internal-virt-agent-uat`
- **Dataset**: `GSO`
- **Table**: `VerificationDisputeList`
- **Partitioning**: Daily by `file_dispute_date`
- **Clustering**: `file_dispute_date`, `vendor_name`, `dispute_category_reason`

The script automatically creates the table with proper configuration if it doesn't exist.

## Monitoring

Check the Apps Script execution logs:
1. In Apps Script editor: **View** → **Logs** (or Ctrl+Enter)
2. Or go to **Executions** for detailed history

## Troubleshooting

### "Sheet not found"
Update `SHEET_NAME` constant to match your sheet tab name.

### "Spreadsheet not found"
Verify `SPREADSHEET_ID` is correct (from the URL of your Google Sheet).

### Date parsing errors
Check the console logs to see which dates couldn't be parsed. Update the source data to use DD/MM/YYYY format.

### Permission errors
Make sure the script has access to:
- Google Sheets (to read data)
- BigQuery (to write data)
- Google Drive (for temp JSON files)
- Script Properties (for smart triggers)

## Performance Benefits

With partitioning and clustering:
- ✅ Date range queries (e.g., disputes from last month) are much faster
- ✅ Filtering by date + vendor is highly optimized
- ✅ Filtering by dispute category is fast
- ✅ Query costs are reduced (scans less data)
- ✅ Looker Studio dashboards load faster

## Manual Execution

To run manually anytime:
```javascript
importVerificationDisputeToBigQuery()
```
