// Dispute Log → BigQuery intelligent import script
// Google Sheet: https://docs.google.com/spreadsheets/d/19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I/edit
// Configure the constants below before first run.
const SPREADSHEET_ID = '19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I';
const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const DATASET_ID = 'GSO'; // Change to your target dataset
const TABLE_ID = 'dispute_log';
const SHEET_NAME = 'DisputeList'; // Change if your sheet tab has a different name
// Composite key - using multiple columns to identify unique disputes
const KEY_COLUMNS = ['is_id', 'invoice_number', 'line']; // IS ID + Invoice + Line# uniquely identifies a dispute
const USE_INGESTION_TIMESTAMP = true;

// Main entry: run manually or from a trigger
function importDisputeLogToBigQuery() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    console.error('Sheet "' + SHEET_NAME + '" not found');
    return;
  }

  const values = sheet.getDataRange().getValues();
  if (!values || values.length < 2) {
    console.log('No data rows found (need header + at least one data row).');
    return;
  }

  const headersRaw = values[0].map(String);
  const headers = headersRaw.map(sanitizeHeader);
  
  // Log the header mapping for debugging
  console.log('Header mapping:');
  for (let i = 0; i < headersRaw.length; i++) {
    console.log('  "' + headersRaw[i] + '" → "' + headers[i] + '"');
  }

  // Ensure target table exists with proper schema
  ensureDisputeTableExists();

  // Build row objects with intelligent parsing
  const rows = [];
  const parseErrors = [];
  
  for (let r = 1; r < values.length; r++) {
    const rowVals = values[r];
    
    // Skip completely empty rows
    if (rowVals.every(c => c === '' || c === null || typeof c === 'undefined')) continue;
    
    // Check if all key columns are empty - if so, skip
    const isIdIdx = headersRaw.findIndex(h => h.toLowerCase().includes('is id'));
    if (isIdIdx >= 0 && !rowVals[isIdIdx]) continue;
    
    try {
      const obj = parseDisputeRow(headersRaw, headers, rowVals, r + 1);
      if (obj) {
        obj._load_uuid = Utilities.getUuid();
        obj._source_row_number = String(r + 1); // Track source row for debugging
        rows.push({ insertId: Utilities.getUuid(), json: obj });
      }
    } catch (err) {
      parseErrors.push({ row: r + 1, error: String(err) });
      console.warn('Row ' + (r + 1) + ' parse error: ' + err);
    }
  }

  if (parseErrors.length > 0) {
    console.warn('Encountered ' + parseErrors.length + ' parse errors. See logs for details.');
  }

  if (rows.length === 0) {
    console.log('No valid data rows to insert after parsing.');
    return;
  }

  console.log('Successfully parsed ' + rows.length + ' rows for import.');

  // Use temp table + MERGE for safe upserts
  const tempTableSuffix = Utilities.getUuid().replace(/-/g, '_');
  const tempTableId = TABLE_ID + '_tmp_' + tempTableSuffix;

  // Create temp table with same schema as target
  createDisputeTempTable(tempTableId);

  // Wait for temp table to exist
  const created = waitForTable(PROJECT_ID, DATASET_ID, tempTableId, 30000);
  if (!created) {
    console.error('Temp table not available after wait; aborting.');
    return;
  }

  // Batch insert into temp table
  const BATCH_SIZE = 500;
  for (let i = 0; i < rows.length; i += BATCH_SIZE) {
    const batch = rows.slice(i, i + BATCH_SIZE);
    const insertBody = { rows: batch };
    try {
      const resp = BigQuery.Tabledata.insertAll(insertBody, PROJECT_ID, DATASET_ID, tempTableId);
      if (resp.insertErrors) {
        // Log first few errors with details
        const errorCount = resp.insertErrors.length;
        console.warn('Batch ' + (Math.floor(i / BATCH_SIZE) + 1) + ': ' + errorCount + ' row(s) failed insertion');
        for (let e = 0; e < Math.min(5, errorCount); e++) {
          const err = resp.insertErrors[e];
          const rowIndex = i + err.index;
          console.error('  Row ' + (rowIndex + 2) + ' (sheet row ' + (rowIndex + 2) + '): ' + 
                        JSON.stringify(err.errors[0]));
        }
        if (errorCount > 5) {
          console.warn('  ... and ' + (errorCount - 5) + ' more errors in this batch');
        }
      } else {
        console.log('Inserted batch ' + (Math.floor(i / BATCH_SIZE) + 1) + ': ' + batch.length + ' rows ✓');
      }
    } catch (err) {
      console.error('BigQuery insertAll failed for temp table batch starting at', i, err);
    }
  }

  // Build and run MERGE SQL
  try {
    const mergeSql = buildDisputeMergeSql(tempTableId);
    console.log('Running MERGE SQL...');
    const jobId = runQueryJob(mergeSql);
    waitForJob(PROJECT_ID, jobId, 600000); // wait up to 10 minutes
    console.log('Merge job completed:', jobId);
  } catch (err) {
    console.error('Merge job failed:', err);
  }

  // Clean up temp table
  try {
    const dropSql = `DROP TABLE \`${PROJECT_ID}.${DATASET_ID}.${tempTableId}\``;
    const dropJobId = runQueryJob(dropSql);
    waitForJob(PROJECT_ID, dropJobId, 120000);
    console.log('Temp table dropped:', tempTableId);
  } catch (e) {
    console.warn('Could not delete temp table (ignored):', e.message || e);
  }

  console.log('Import complete. ' + rows.length + ' rows processed.');
}

// Parse a single dispute row with intelligent data type handling
function parseDisputeRow(headersRaw, headers, rowVals, rowNum) {
  const obj = {};
  
  for (let c = 0; c < headers.length; c++) {
    const fieldName = headers[c];
    const rawValue = rowVals[c];
    const headerRaw = headersRaw[c];
    
    // Handle null/undefined
    if (rawValue === null || typeof rawValue === 'undefined' || rawValue === '') {
      obj[fieldName] = null;
      continue;
    }
    
    // Intelligent type conversion based on field name
    try {
      // DATE FIELDS - intelligent date parsing
      if (headerRaw.toLowerCase().includes('date')) {
        obj[fieldName] = parseFlexibleDate(rawValue, rowNum, headerRaw);
      }
      // NUMERIC FIELDS - amounts, exchange rates, line numbers, days
      else if (headerRaw.toLowerCase().includes('amount') ||
               headerRaw.toLowerCase().includes('exchange rate') ||
               headerRaw.toLowerCase().includes('line #') ||
               headerRaw.toLowerCase().includes('days of')) {
        obj[fieldName] = parseNumeric(rawValue);
      }
      // STRING FIELDS - everything else
      else {
        obj[fieldName] = cleanString(rawValue);
      }
    } catch (err) {
      console.warn('Row ' + rowNum + ', column "' + headerRaw + '" parse warning: ' + err + '. Using null.');
      obj[fieldName] = null;
    }
  }
  
  return obj;
}

// Intelligent date parser that handles multiple formats
function parseFlexibleDate(val, rowNum, columnName) {
  if (!val) return null;
  
  // If already a Date object from Sheets
  if (val instanceof Date) {
    return formatDateForBQ(val);
  }
  
  const str = String(val).trim();
  if (!str) return null;
  
  // Try multiple date formats
  let date = null;
  
  // Format: "1/1/2024" or "1-1-2024" or "1.1.2024"
  const slashDashDot = /^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/;
  const match1 = str.match(slashDashDot);
  if (match1) {
    const month = parseInt(match1[1], 10);
    const day = parseInt(match1[2], 10);
    const year = parseInt(match1[3], 10);
    date = new Date(year, month - 1, day);
  }
  
  // Format: "1-Jun-23" or "1-Sept-23" or "30-Dec-2023"
  const monthNames = {
    'jan': 0, 'january': 0,
    'feb': 1, 'february': 1,
    'mar': 2, 'march': 2,
    'apr': 3, 'april': 3,
    'may': 4,
    'jun': 5, 'june': 5,
    'jul': 6, 'july': 6,
    'aug': 7, 'august': 7,
    'sep': 8, 'sept': 8, 'september': 8,
    'oct': 9, 'october': 9,
    'nov': 10, 'november': 10,
    'dec': 11, 'december': 11
  };
  
  const monthFormat = /^(\d{1,2})[\/\-]([a-z]+)[\/\-](\d{2,4})$/i;
  const match2 = str.match(monthFormat);
  if (match2) {
    const day = parseInt(match2[1], 10);
    const monthStr = match2[2].toLowerCase();
    let year = parseInt(match2[3], 10);
    
    // Handle 2-digit years: assume 20xx for years < 50, 19xx for >= 50
    if (year < 50) year += 2000;
    else if (year < 100) year += 1900;
    
    const month = monthNames[monthStr];
    if (month !== undefined) {
      date = new Date(year, month, day);
    }
  }
  
  // Fallback: try native Date parsing
  if (!date) {
    date = new Date(str);
    if (isNaN(date.getTime())) {
      const rowInfo = rowNum ? ' (Row ' + rowNum + ', Column "' + columnName + '")' : '';
      console.warn('Could not parse date: "' + str + '"' + rowInfo);
      return null;
    }
  }
  
  return formatDateForBQ(date);
}

// Format Date object as YYYY-MM-DD for BigQuery DATE type
function formatDateForBQ(date) {
  if (!date || isNaN(date.getTime())) return null;
  
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  
  return year + '-' + month + '-' + day;
}

// Parse numeric values, handling currency symbols and commas
function parseNumeric(val) {
  if (val === null || val === undefined || val === '') return null;
  
  let num;
  if (typeof val === 'number') {
    num = val;
  } else {
    const str = String(val).trim();
    if (!str) return null;
    
    // Remove currency symbols, commas, and spaces
    const cleaned = str.replace(/[$€£¥,\s]/g, '');
    
    // Handle dash as zero
    if (cleaned === '-' || cleaned === '—') return null;
    
    num = parseFloat(cleaned);
    if (isNaN(num)) {
      console.warn('Could not parse numeric value: "' + str + '"');
      return null;
    }
  }
  
  // Round to 6 decimal places to avoid floating-point precision errors
  // BigQuery NUMERIC supports up to 38 digits, but we want to avoid errors like 248.24799999999996
  const rounded = Math.round(num * 1000000) / 1000000;
  
  return String(rounded);
}

// Clean string values
function cleanString(val) {
  if (val === null || val === undefined) return null;
  
  const str = String(val).trim();
  
  // Treat dash as null
  if (str === '-' || str === '—') return null;
  
  return str || null;
}

// Create the main dispute table with proper schema
function ensureDisputeTableExists() {
  let tableExists = false;
  try {
    BigQuery.Tables.get(PROJECT_ID, DATASET_ID, TABLE_ID);
    tableExists = true;
    console.log('Table ' + TABLE_ID + ' already exists.');
  } catch (e) {
    if (!isNotFoundError(e)) throw e;
  }

  if (!tableExists) {
    console.log('Creating table ' + TABLE_ID + '...');
    const schemaFields = getDisputeTableSchema();
    const tableResource = {
      tableReference: {
        projectId: PROJECT_ID,
        datasetId: DATASET_ID,
        tableId: TABLE_ID
      },
      schema: { fields: schemaFields }
    };
    
    BigQuery.Tables.insert(tableResource, PROJECT_ID, DATASET_ID);
    console.log('Created table ' + TABLE_ID + ' with proper schema.');
  }
}

// Define the BigQuery schema for dispute log
function getDisputeTableSchema() {
  return [
    { name: 'file_dispute_date', type: 'DATE', mode: 'NULLABLE' },
    { name: 'is_id', type: 'STRING', mode: 'NULLABLE' },
    { name: 'charged_company', type: 'STRING', mode: 'NULLABLE' },
    { name: 'vendor_name', type: 'STRING', mode: 'NULLABLE' },
    { name: 'vendor_code', type: 'STRING', mode: 'NULLABLE' },
    { name: 'invoice_number', type: 'STRING', mode: 'NULLABLE' },
    { name: 'line', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'circuit_id', type: 'STRING', mode: 'NULLABLE' },
    { name: 'po_no', type: 'STRING', mode: 'NULLABLE' },
    { name: 'charge_date_from', type: 'DATE', mode: 'NULLABLE' },
    { name: 'charge_date_to', type: 'DATE', mode: 'NULLABLE' },
    { name: 'invoice_currency', type: 'STRING', mode: 'NULLABLE' },
    { name: 'line_amount', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'dispute_amount_in_local_currency', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'exchange_rate', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'dispute_amount_in_usd', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'dispute_category_reason', type: 'STRING', mode: 'NULLABLE' },
    { name: 'dispute_details', type: 'STRING', mode: 'NULLABLE' },
    { name: 'follow_up_action_remarks', type: 'STRING', mode: 'NULLABLE' },
    { name: 'ticket_case_no_if_any', type: 'STRING', mode: 'NULLABLE' },
    { name: 'credit_note_reference', type: 'STRING', mode: 'NULLABLE' },
    { name: 'received_credit_amount_in_local_currency', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'received_credit_amount_in_usd', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'dispute_resolve_date', type: 'DATE', mode: 'NULLABLE' },
    { name: 'diff_btw_forecast_and_actual_credit_amount_local_currency', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'diff_btw_forecast_and_actual_credit_amount_usd', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'name_of_verifier', type: 'STRING', mode: 'NULLABLE' },
    { name: 'days_of_resovled', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'actual_days_of_resolved', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'vendor_group_name', type: 'STRING', mode: 'NULLABLE' },
    { name: 'dispute_reason', type: 'STRING', mode: 'NULLABLE' },
    { name: '_source_row_number', type: 'STRING', mode: 'NULLABLE' },
    { name: 'ingestion_time', type: 'TIMESTAMP', mode: 'NULLABLE' }
  ];
}

// Create temp table with same schema as main table
function createDisputeTempTable(tempTableId) {
  const schemaFields = getDisputeTableSchema();
  // Add _load_uuid to temp table
  schemaFields.push({ name: '_load_uuid', type: 'STRING', mode: 'NULLABLE' });
  
  const tableResource = {
    tableReference: {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      tableId: tempTableId
    },
    schema: { fields: schemaFields }
  };
  
  BigQuery.Tables.insert(tableResource, PROJECT_ID, DATASET_ID);
  console.log('Created temp table ' + tempTableId);
}

// Build MERGE SQL with composite key
function buildDisputeMergeSql(tempTableId) {
  const targetFqn = '`' + PROJECT_ID + '.' + DATASET_ID + '.' + TABLE_ID + '`';
  const tempFqn = '`' + PROJECT_ID + '.' + DATASET_ID + '.' + tempTableId + '`';
  
  // Build composite key join condition
  const keyConditions = KEY_COLUMNS.map(k => 'T.' + k + ' = S.' + k).join(' AND ');
  
  // Dedup source by composite key
  const partitionBy = KEY_COLUMNS.join(', ');
  const dedupSource = `(
    SELECT * FROM ${tempFqn}
    WHERE ${KEY_COLUMNS.map(k => k + ' IS NOT NULL').join(' AND ')}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ${partitionBy} ORDER BY _load_uuid DESC) = 1
  )`;
  
  // Get all columns from schema except ingestion_time
  const schema = getDisputeTableSchema();
  const updateCols = schema
    .filter(f => f.name !== 'ingestion_time')
    .map(f => f.name);
  
  const updateSet = updateCols.map(c => 'T.' + c + ' = S.' + c).join(',\n    ');
  const updateSetWithTimestamp = updateSet + ',\n    T.ingestion_time = CURRENT_TIMESTAMP()';
  
  const insertCols = updateCols.concat(['ingestion_time']).join(', ');
  const insertVals = updateCols.map(c => 'S.' + c).concat(['CURRENT_TIMESTAMP()']).join(', ');
  
  const sql = `MERGE ${targetFqn} T
USING ${dedupSource} S
ON ${keyConditions}
WHEN MATCHED THEN
  UPDATE SET
    ${updateSetWithTimestamp}
WHEN NOT MATCHED THEN
  INSERT (${insertCols})
  VALUES (${insertVals})`;
  
  return sql;
}

// Helper functions (reused from existing pattern)

function sanitizeHeader(orig) {
  let s = String(orig || '').trim();
  if (s.length === 0) s = 'field';
  s = s.replace(/[^\w]/g, '_');
  s = s.replace(/^(\d+)/, 'f_$1');
  s = s.replace(/__+/g, '_');
  s = s.replace(/^_+|_+$/g, ''); // Remove leading/trailing underscores
  s = s.toLowerCase();
  if (!/^[A-Za-z_]/.test(s)) s = 'f_' + s;
  return s.substring(0, 128);
}

function isNotFoundError(e) {
  if (!e) return false;
  const msg = String(e.message || e);
  return msg.indexOf('Not found') !== -1 || 
         msg.indexOf('Not Found') !== -1 || 
         msg.indexOf('404') !== -1 ||
         (e.code && e.code === 404);
}

function waitForTable(projectId, datasetId, tableId, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      BigQuery.Tables.get(projectId, datasetId, tableId);
      return true;
    } catch (e) {
      if (!isNotFoundError(e)) throw e;
      Utilities.sleep(2000);
    }
  }
  return false;
}

function runQueryJob(sql) {
  const job = {
    configuration: {
      query: {
        query: sql,
        useLegacySql: false
      }
    }
  };
  const resp = BigQuery.Jobs.insert(job, PROJECT_ID);
  return resp.jobReference.jobId;
}

function waitForJob(projectId, jobId, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const job = BigQuery.Jobs.get(projectId, jobId);
    const status = job.status;
    if (status && status.state === 'DONE') {
      if (status.errorResult) {
        throw new Error('Query job failed: ' + JSON.stringify(status.errorResult));
      }
      return job;
    }
    Utilities.sleep(2000);
  }
  throw new Error('Job ' + jobId + ' did not complete within timeout');
}

// Create a daily trigger (example: every day at 02:00). Call once manually.
function createDailyTrigger() {
  ScriptApp.newTrigger('importDisputeLogToBigQuery')
    .timeBased()
    .everyDays(1)
    .atHour(2)
    .create();
  console.log('Daily trigger created: importDisputeLogToBigQuery every day at 02:00');
}

// SMART UPDATE TRIGGER - Runs 15 minutes after last sheet edit
// Call this once to set up the smart update system
function setupSmartUpdateTrigger() {
  // Remove any existing triggers for these functions
  deleteExistingTriggers();
  
  // Create onEdit trigger to track when sheet is modified
  ScriptApp.newTrigger('onSheetEdit')
    .forSpreadsheet(SPREADSHEET_ID)
    .onEdit()
    .create();
  
  // Create time-based trigger that checks every 15 minutes
  ScriptApp.newTrigger('checkAndRunIfEdited')
    .timeBased()
    .everyMinutes(15)
    .create();
  
  console.log('Smart update trigger system created:');
  console.log('- Sheet edit tracker: active');
  console.log('- Auto-run check: every 15 minutes');
}

// Called automatically when sheet is edited (tracks last edit time)
function onSheetEdit(e) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('lastEditTime', Date.now().toString());
  console.log('Sheet edited at: ' + new Date().toISOString());
}

// Called every 15 minutes - runs import if sheet was edited since last run
function checkAndRunIfEdited() {
  const props = PropertiesService.getScriptProperties();
  const lastEditTime = props.getProperty('lastEditTime');
  const lastRunTime = props.getProperty('lastRunTime');
  
  if (!lastEditTime) {
    console.log('No edits detected since trigger setup.');
    return;
  }
  
  const editTime = parseInt(lastEditTime, 10);
  const runTime = lastRunTime ? parseInt(lastRunTime, 10) : 0;
  
  // If there was an edit since last run, execute import
  if (editTime > runTime) {
    const minutesSinceEdit = Math.floor((Date.now() - editTime) / 60000);
    console.log('Sheet was edited ' + minutesSinceEdit + ' minutes ago. Running import...');
    
    importDisputeLogToBigQuery();
    
    // Update last run time
    props.setProperty('lastRunTime', Date.now().toString());
  } else {
    console.log('No new edits since last run. Skipping import.');
  }
}

// Remove existing triggers for this function
function deleteExistingTriggers() {
  const all = ScriptApp.getProjectTriggers();
  const functionsToRemove = ['importDisputeLogToBigQuery', 'onSheetEdit', 'checkAndRunIfEdited'];
  
  for (let t of all) {
    if (functionsToRemove.includes(t.getHandlerFunction())) {
      ScriptApp.deleteTrigger(t);
    }
  }
  console.log('Existing triggers removed.');
}
