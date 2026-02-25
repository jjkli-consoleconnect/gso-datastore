// Verification Dispute → BigQuery intelligent import script
// Configure the constants below before first run.
const SPREADSHEET_ID = '19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I';
const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const DATASET_ID = 'GSO';
const TABLE_ID = 'VerificationDisputeList';
const SHEET_NAME = 'DisputeList';
const TEMP_FOLDER_ID = '1owI6KYtZIPCZf_hyksxBQ0a4IdXhBQld'; // Temp folder for JSON files

// Main entry: run manually or from a trigger
function importVerificationDisputeToBigQuery() {
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
  ensureVerificationDisputeTableExists();

  // Build row objects with intelligent parsing
  const rows = [];
  const parseErrors = [];
  
  for (let r = 1; r < values.length; r++) {
    const rowVals = values[r];
    
    // Skip completely empty rows
    if (rowVals.every(c => c === '' || c === null || typeof c === 'undefined')) continue;
    
    // Check if all key columns are empty - if so, skip
    const isIdIdx = headersRaw.findIndex(h => h.toLowerCase().includes('is') && h.toLowerCase().includes('id'));
    if (isIdIdx >= 0 && !rowVals[isIdIdx]) continue;
    
    try {
      const obj = parseVerificationDisputeRow(headersRaw, headers, rowVals, r + 1);
      if (obj) {
        obj._source_row_number = String(r + 1);
        obj.ingestion_time = new Date().toISOString(); // Add timestamp
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

  // Convert rows to newline-delimited JSON
  const jsonData = rows.map(r => JSON.stringify(r.json)).join('\n');
  const jsonFileName = 'VerificationDispute_' + new Date().getTime() + '.json';
  
  // Upload JSON to temp folder
  const tempFolder = DriveApp.getFolderById(TEMP_FOLDER_ID);
  const jsonFile = tempFolder.createFile(jsonFileName, jsonData);
  console.log('Created temp JSON file: ' + jsonFileName);
  
  // Load JSON to BigQuery with WRITE_TRUNCATE (overwrites table)
  try {
    const jsonDataBlob = jsonFile.getBlob();
    const loadJob = {
      configuration: {
        load: {
          destinationTable: { 
            projectId: PROJECT_ID, 
            datasetId: DATASET_ID, 
            tableId: TABLE_ID 
          },
          sourceFormat: 'NEWLINE_DELIMITED_JSON',
          writeDisposition: 'WRITE_TRUNCATE', // Overwrites entire table
          autodetect: false, // Use existing schema
          schema: { fields: getVerificationDisputeTableSchema() }
        }
      }
    };
    
    console.log('Loading data to BigQuery (overwriting table)...');
    const job = BigQuery.Jobs.insert(loadJob, PROJECT_ID, jsonDataBlob);
    waitForJob(PROJECT_ID, job.jobReference.jobId, 600000);
    console.log('Load job completed successfully');
  } catch (err) {
    console.error('BigQuery load failed:', err);
    throw err;
  } finally {
    // Clean up temp JSON file
    try {
      jsonFile.setTrashed(true);
      console.log('Temp JSON file deleted');
    } catch (e) {
      console.warn('Could not delete temp JSON file:', e);
    }
  }

  console.log('Import complete. ' + rows.length + ' rows processed.');
}

// Parse a single verification dispute row with intelligent data type handling
function parseVerificationDisputeRow(headersRaw, headers, rowVals, rowNum) {
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
               headerRaw.toLowerCase().includes('line') ||
               headerRaw.toLowerCase().includes('days')) {
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
  
  // Format: DD/MM/YYYY (most common based on sample data)
  let match = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (match) {
    const day = parseInt(match[1], 10);
    const month = parseInt(match[2], 10);
    const year = parseInt(match[3], 10);
    date = new Date(Date.UTC(year, month - 1, day));
  }
  
  // Format: DD-MM-YYYY
  if (!date || isNaN(date.getTime())) {
    match = str.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
    if (match) {
      const day = parseInt(match[1], 10);
      const month = parseInt(match[2], 10);
      const year = parseInt(match[3], 10);
      date = new Date(Date.UTC(year, month - 1, day));
    }
  }
  
  // Format: "1 Jan 2024" or "01 Jan 2024"
  if (!date || isNaN(date.getTime())) {
    match = str.match(/^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$/);
    if (match) {
      const monthNames = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                          'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
      const monthIdx = monthNames.indexOf(match[2].toLowerCase());
      if (monthIdx >= 0) {
        const day = parseInt(match[1], 10);
        const year = parseInt(match[3], 10);
        date = new Date(Date.UTC(year, monthIdx, day));
      }
    }
  }
  
  // Format: YYYY-MM-DD (ISO format)
  if (!date || isNaN(date.getTime())) {
    match = str.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (match) {
      const year = parseInt(match[1], 10);
      const month = parseInt(match[2], 10);
      const day = parseInt(match[3], 10);
      date = new Date(Date.UTC(year, month - 1, day));
    }
  }
  
  // Last resort: try native Date parsing
  if (!date || isNaN(date.getTime())) {
    date = new Date(str);
  }
  
  // If still invalid, log warning and return null
  if (!date || isNaN(date.getTime())) {
    console.warn('Row ' + rowNum + ': Could not parse date "' + str + '" in column "' + columnName + '"');
    return null;
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
    
    // Handle dash as null
    if (cleaned === '-' || cleaned === '—') return null;
    
    num = parseFloat(cleaned);
    if (isNaN(num)) {
      console.warn('Could not parse numeric value: "' + str + '"');
      return null;
    }
  }
  
  // Round to 6 decimal places to avoid floating-point precision errors
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

// Create the main verification dispute table with proper schema
function ensureVerificationDisputeTableExists() {
  // Delete table if it exists (to replace EXTERNAL table with native table)
  try {
    BigQuery.Tables.get(PROJECT_ID, DATASET_ID, TABLE_ID);
    console.log('Table ' + TABLE_ID + ' exists. Deleting to recreate as native table...');
    BigQuery.Tables.remove(PROJECT_ID, DATASET_ID, TABLE_ID);
    console.log('Table deleted successfully.');
    Utilities.sleep(2000); // Wait for deletion to propagate
  } catch (e) {
    if (!isNotFoundError(e)) throw e;
    console.log('Table does not exist. Will create new table.');
  }

  // Create new native table with partitioning and clustering
  console.log('Creating table ' + TABLE_ID + '...');
  const schemaFields = getVerificationDisputeTableSchema();
  const tableResource = {
    tableReference: {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      tableId: TABLE_ID
    },
    schema: { fields: schemaFields },
    // Partition by File_Dispute_Date for better performance
    timePartitioning: {
      type: 'DAY',
      field: 'File_Dispute_Date'
    },
    // Cluster by commonly filtered fields
    clustering: {
      fields: ['File_Dispute_Date', 'Vendor_Name', 'Dispute_Category__Reason']
    }
  };
  
  BigQuery.Tables.insert(tableResource, PROJECT_ID, DATASET_ID);
  console.log('Created table ' + TABLE_ID + ' with schema, partitioning, and clustering.');
  Utilities.sleep(2000); // Wait for table creation to propagate
}

// Define the BigQuery schema for verification dispute
function getVerificationDisputeTableSchema() {
  return [
    { name: 'File_Dispute_Date', type: 'DATE', mode: 'NULLABLE' },
    { name: 'IS_ID', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Charged_Company', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Vendor_Name', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Vendor_Code', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Invoice__Number', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Line__', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'circuit_ID', type: 'STRING', mode: 'NULLABLE' },
    { name: 'PO_no_', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Charge_Date_From', type: 'DATE', mode: 'NULLABLE' },
    { name: 'Charge_Date_To', type: 'DATE', mode: 'NULLABLE' },
    { name: 'Invoice_Currency', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Line_Amount', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Dispute_Amount_in_local_currency', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Exchange_rate', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Dispute_Amount_in_USD', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Dispute_Category__Reason', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Dispute_Details', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Follow_up_action___Remarks', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Ticket__case_no__if_any', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Credit_Note_Reference', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Received_Credit_Amount_in_local_currency', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Received_Credit_Amount_in_USD', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Dispute_Resolve_Date', type: 'DATE', mode: 'NULLABLE' },
    { name: 'Diff_btw_forecast_and_actual_credit_Amount__local_currency_', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Diff_btw_forecast_and_actual_credit_Amount__USD_', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Name_of_verifier', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Days_of_Resovled', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Actual_Days_of_Resolved', type: 'NUMERIC', mode: 'NULLABLE' },
    { name: 'Vendor_Group_Name', type: 'STRING', mode: 'NULLABLE' },
    { name: 'Dispute_Reason', type: 'STRING', mode: 'NULLABLE' },
    { name: '_source_row_number', type: 'STRING', mode: 'NULLABLE' },
    { name: 'ingestion_time', type: 'TIMESTAMP', mode: 'NULLABLE' }
  ];
}



// Map Google Sheets column headers to exact BigQuery field names
function sanitizeHeader(orig) {
  const s = String(orig || '').trim();
  
  // Exact mapping from Google Sheets headers to BigQuery field names
  const headerMap = {
    'File Dispute Date': 'File_Dispute_Date',
    'IS ID': 'IS_ID',
    'Charged Company': 'Charged_Company',
    'Vendor Name': 'Vendor_Name',
    'Vendor Code': 'Vendor_Code',
    'Invoice  Number': 'Invoice__Number',  // Note: double space in sheet → double underscore in BQ
    'Line #': 'Line__',
    'circuit ID': 'circuit_ID',
    'PO no.': 'PO_no_',
    'Charge Date From': 'Charge_Date_From',
    'Charge Date To': 'Charge_Date_To',
    'Invoice Currency': 'Invoice_Currency',
    'Line Amount': 'Line_Amount',
    'Dispute Amount in local currency': 'Dispute_Amount_in_local_currency',
    'Exchange rate': 'Exchange_rate',
    'Dispute Amount in USD': 'Dispute_Amount_in_USD',
    'Dispute Category/ Reason': 'Dispute_Category__Reason',  // Note: slash → double underscore
    'Dispute Details': 'Dispute_Details',
    'Follow up action / Remarks': 'Follow_up_action___Remarks',  // Note: slash → triple underscore
    'Ticket/ case no. if any': 'Ticket__case_no__if_any',  // Note: slash → double underscore
    'Credit Note Reference': 'Credit_Note_Reference',
    'Received Credit Amount in local currency': 'Received_Credit_Amount_in_local_currency',
    'Received Credit Amount in USD': 'Received_Credit_Amount_in_USD',
    'Dispute Resolve Date': 'Dispute_Resolve_Date',
    'Diff btw forecast and actual credit Amount (local currency)': 'Diff_btw_forecast_and_actual_credit_Amount__local_currency_',  // Note: parens → double underscore
    'Diff btw forecast and actual credit Amount (USD)': 'Diff_btw_forecast_and_actual_credit_Amount__USD_',
    'Name of verifier': 'Name_of_verifier',
    'Days of Resovled': 'Days_of_Resovled',  // Note: keeping original typo
    'Actual Days of Resolved': 'Actual_Days_of_Resolved',
    'Vendor Group Name': 'Vendor_Group_Name',
    'Dispute Reason': 'Dispute_Reason'
  };
  
  // Return exact mapped name if exists
  if (headerMap.hasOwnProperty(s)) {
    return headerMap[s];
  }
  
  // Fallback: basic sanitization for unexpected columns
  let result = s.replace(/[^\w]/g, '_');
  result = result.replace(/^(\d+)/, 'f_$1');
  result = result.replace(/__+/g, '_');
  result = result.replace(/^_+|_+$/g, '');
  if (!/^[A-Za-z_]/.test(result)) result = 'f_' + result;
  return result.substring(0, 128);
}

function isNotFoundError(e) {
  if (!e) return false;
  const msg = String(e.message || e);
  return msg.indexOf('Not found') !== -1 || 
         msg.indexOf('Not Found') !== -1 || 
         msg.indexOf('404') !== -1 ||
         (e.code && e.code === 404);
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
  ScriptApp.newTrigger('importVerificationDisputeToBigQuery')
    .timeBased()
    .everyDays(1)
    .atHour(2)
    .create();
  console.log('Daily trigger created: importVerificationDisputeToBigQuery every day at 02:00');
}

// SMART UPDATE TRIGGER - Runs 5 minutes after last sheet edit
// Call this once to set up the smart update system
function setupSmartUpdateTrigger() {
  // Remove any existing triggers for these functions
  deleteExistingTriggers();
  
  // Create onEdit trigger to track when sheet is modified
  ScriptApp.newTrigger('onSheetEdit')
    .forSpreadsheet(SPREADSHEET_ID)
    .onEdit()
    .create();
  
  // Create time-based trigger that checks every 1 minute
  ScriptApp.newTrigger('checkAndRunIfEdited')
    .timeBased()
    .everyMinutes(1)
    .create();
  
  console.log('Smart update trigger system created:');
  console.log('- Sheet edit tracker: active');
  console.log('- Auto-run check: every 1 minute (runs 5 minutes after last edit)');
}

// Called automatically when sheet is edited (tracks last edit time)
function onSheetEdit(e) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('lastEditTime', Date.now().toString());
  console.log('Sheet edited at: ' + new Date().toISOString());
}

// Called every minute - runs import if sheet was edited and 5 minutes have passed
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
  const now = Date.now();
  const minutesSinceEdit = Math.floor((now - editTime) / 60000);
  
  // Only run if:
  // 1. There was an edit since last run
  // 2. At least 5 minutes have passed since the last edit (to avoid running during active editing)
  if (editTime > runTime) {
    if (minutesSinceEdit >= 5) {
      console.log('Sheet was last edited ' + minutesSinceEdit + ' minutes ago. Running import...');
      
      importVerificationDisputeToBigQuery();
      
      // Update last run time
      props.setProperty('lastRunTime', Date.now().toString());
    } else {
      console.log('Sheet was edited ' + minutesSinceEdit + ' minutes ago. Waiting for 5-minute quiet period...');
    }
  } else {
    console.log('No new edits since last run. Skipping import.');
  }
}

// Remove existing triggers for this function
function deleteExistingTriggers() {
  const all = ScriptApp.getProjectTriggers();
  const functionsToRemove = ['importVerificationDisputeToBigQuery', 'onSheetEdit', 'checkAndRunIfEdited'];
  
  for (let t of all) {
    if (functionsToRemove.includes(t.getHandlerFunction())) {
      ScriptApp.deleteTrigger(t);
    }
  }
  console.log('Existing triggers removed.');
}
