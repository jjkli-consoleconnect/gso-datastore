# Dispute Log to BigQuery - Intelligent Import Script

## Overview
This Google Apps Script intelligently imports dispute log data from a Google Sheet into BigQuery, handling data integrity issues common with user-input spreadsheets.

**Source Sheet:** https://docs.google.com/spreadsheets/d/19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I/edit

## Key Features

### 1. **Intelligent Date Parsing**
Handles multiple date formats automatically:
- `1/1/2024` - Standard slash format
- `1-Jun-23` - Month name with 2-digit year
- `30-Sept-23` - Abbreviated month names
- `10-Jan-24` - Mixed formats
- Native Google Sheets date objects

Auto-converts 2-digit years (assumes 20xx for <50, 19xx for >=50)

### 2. **Data Validation & Cleaning**
- **Empty rows:** Automatically skipped
- **Numeric fields:** Strips currency symbols ($, €, £, ¥), commas, and spaces
- **String fields:** Trims whitespace, treats dashes (-) as null
- **Error handling:** Logs parse errors with row numbers for troubleshooting

### 3. **Proper BigQuery Schema**
Creates table with appropriate data types:
- **DATE:** All date fields (file_dispute_date, charge_date_from, dispute_resolve_date, etc.)
- **NUMERIC:** Amounts, exchange rate, line numbers, days
- **STRING:** Text fields (names, IDs, descriptions)
- **TIMESTAMP:** Auto-added ingestion_time for tracking

### 4. **Reliable Upserts**
- Uses **composite key** (IS ID + Invoice Number + Line #) to identify unique disputes
- **Temp table + MERGE** pattern prevents data loss during updates
- Deduplicates within source data before merge
- Tracks source row numbers for debugging

### 5. **Looker Studio Ready**
- Clean, consistent data types for reliable visualization
- Ingestion timestamp for tracking data freshness
- Null handling prevents chart breaks

## Setup Instructions

### Step 1: Configure Constants
Edit these values at the top of `Code.gs`:

```javascript
const PROJECT_ID = 'pccw-internal-virt-agent-uat'; // Your GCP project
const DATASET_ID = 'GSO'; // Your BigQuery dataset
const TABLE_ID = 'dispute_log'; // Target table name
const SHEET_NAME = 'DisputeList'; // Your sheet tab name
```

### Step 2: Enable BigQuery API
1. In Apps Script editor, click **Services** (⊕)
2. Find **BigQuery API** and add it
3. Identifier should be `BigQuery`

### Step 3: Set Up GCP Permissions
Ensure your Google Account has these BigQuery permissions:
- `bigquery.tables.create`
- `bigquery.tables.updateData`
- `bigquery.jobs.create`

Or assign role: `BigQuery Data Editor`

### Step 4: First Run
1. Open Apps Script editor
2. Select function: `importDisputeLogToBigQuery`
3. Click **Run**
4. Authorize when prompted
5. Check **Execution log** for progress

### Step 5: Set Up Automation (Optional)

#### Option A: Smart Update Trigger (Recommended)
Runs automatically 15 minutes after sheet edits (avoids multiple runs during rapid edits):
1. Select function: `setupSmartUpdateTrigger`
2. Click **Run**
3. Verify in **Triggers** menu (clock icon) - you'll see 2 triggers:
   - `onSheetEdit` - tracks when sheet is modified
   - `checkAndRunIfEdited` - runs every 15 minutes, imports only if edited

**How it works:** 
- When you edit the sheet, it records the edit time
- Every 15 minutes, it checks if there were edits since last run
- If yes, runs the import
- If no, skips (saves quota)

#### Option B: Daily Schedule
To run automatically daily at 2 AM:
1. Select function: `createDailyTrigger`
2. Click **Run**
3. Verify in **Triggers** menu (clock icon)

#### Remove Triggers
To remove all automation:
- Run function: `deleteExistingTriggers`

## How It Works

### Data Flow
```
Google Sheet → Parse & Validate → Temp Table → MERGE → Production Table
```

1. **Read:** Gets all data from specified sheet tab
2. **Parse:** Intelligently converts each field to proper type
3. **Validate:** Skips empty rows, logs errors
4. **Temp Table:** Creates temporary staging table
5. **Insert:** Batch inserts into temp table (500 rows/batch)
6. **Merge:** Upserts from temp to production using composite key
7. **Cleanup:** Drops temp table

### Composite Key Logic
A dispute is uniquely identified by:
- `is_id` (IS ID)
- `invoice_number` (Invoice Number)
- `line` (Line #)

When these three match, the row is **updated**. Otherwise, it's **inserted** as new.

### Date Parsing Examples
```
Input              → Output (YYYY-MM-DD)
"1/1/2024"        → "2024-01-01"
"1-Jun-23"        → "2023-06-01"
"30-Sept-23"      → "2023-09-30"
"10-Jan-24"       → "2024-01-10"
Date(2024,0,15)   → "2024-01-15"
```

### Numeric Parsing Examples
```
Input         → Output
"$1,234.56"  → "1234.56"
"€ 400"      → "400"
"1.23"       → "1.23"
"-"          → null
""           → null
```

## Troubleshooting

### View Execution Logs
1. Apps Script editor → **Executions** (clock icon)
2. Click on a run to see logs
3. Look for parse errors or BigQuery errors

### Common Issues

**Issue:** "Table not found"
- **Fix:** Run script once to create table automatically

**Issue:** "Parse errors for some rows"
- **Fix:** Check execution log for row numbers with errors
- Invalid dates or numbers will be stored as null

**Issue:** "Permission denied"
- **Fix:** Ensure GCP permissions are set correctly
- Try running script again to re-authorize

**Issue:** "Duplicate rows"
- **Fix:** Script automatically deduplicates by composite key
- Last occurrence wins for duplicates in same run

### Data Quality Checks
After import, run this in BigQuery to check quality:

```sql
-- Check for null key columns
SELECT *
FROM `pccw-internal-virt-agent-uat.GSO.dispute_log`
WHERE is_id IS NULL OR invoice_number IS NULL OR line IS NULL;

-- Check date parsing success rate
SELECT
  COUNTIF(file_dispute_date IS NOT NULL) / COUNT(*) as date_parse_rate,
  COUNTIF(charge_date_from IS NOT NULL) / COUNT(*) as charge_from_parse_rate,
  COUNTIF(dispute_resolve_date IS NOT NULL) / COUNT(*) as resolve_date_parse_rate
FROM `pccw-internal-virt-agent-uat.GSO.dispute_log`;

-- Check ingestion freshness
SELECT
  MAX(ingestion_time) as last_update,
  COUNT(*) as total_rows
FROM `pccw-internal-virt-agent-uat.GSO.dispute_log`;
```

## Schema Reference

| Field Name | Type | Description |
|------------|------|-------------|
| file_dispute_date | DATE | When dispute was filed |
| is_id | STRING | Internal system ID (part of key) |
| charged_company | STRING | Company being charged |
| vendor_name | STRING | Vendor name |
| vendor_code | STRING | Vendor identifier |
| invoice_number | STRING | Invoice number (part of key) |
| line | NUMERIC | Line item number (part of key) |
| circuit_id | STRING | Circuit identifier |
| po_no | STRING | Purchase order number |
| charge_date_from | DATE | Charge period start |
| charge_date_to | DATE | Charge period end |
| invoice_currency | STRING | Currency code (EUR, USD, etc.) |
| line_amount | NUMERIC | Line item amount |
| dispute_amount_in_local_currency | NUMERIC | Disputed amount (local) |
| exchange_rate | NUMERIC | Exchange rate to USD |
| dispute_amount_in_usd | NUMERIC | Disputed amount (USD) |
| dispute_category_reason | STRING | Dispute category |
| dispute_details | STRING | Detailed description |
| follow_up_action_remarks | STRING | Follow-up notes |
| ticket_case_no_if_any | STRING | Related ticket/case |
| credit_note_reference | STRING | Credit note number |
| received_credit_amount_in_local_currency | NUMERIC | Credit received (local) |
| received_credit_amount_in_usd | NUMERIC | Credit received (USD) |
| dispute_resolve_date | DATE | Resolution date |
| diff_btw_forecast_and_actual_credit_amount_local_currency | NUMERIC | Forecast vs actual diff (local) |
| diff_btw_forecast_and_actual_credit_amount_usd | NUMERIC | Forecast vs actual diff (USD) |
| name_of_verifier | STRING | Who verified the dispute |
| days_of_resovled | NUMERIC | Days to resolve (forecast) |
| actual_days_of_resolved | NUMERIC | Actual days to resolve |
| vendor_group_name | STRING | Vendor group |
| dispute_reason | STRING | Reason for dispute |
| _source_row_number | STRING | Original sheet row number (for debugging) |
| ingestion_time | TIMESTAMP | When data was loaded |

## Performance

- **Batch size:** 500 rows per BigQuery insert
- **Typical runtime:** 30-90 seconds for 1000 rows
- **Max sheet size:** ~50,000 rows (Google Apps Script limits)

For larger datasets, consider splitting by year or using BigQuery Data Transfer Service.

## Support

For issues or questions:
1. Check execution logs first
2. Verify BigQuery permissions
3. Test with a small sample of data
4. Review data quality checks above
