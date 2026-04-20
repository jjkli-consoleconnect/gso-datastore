// Dispute Log → BigQuery intelligent import script
// Google Sheet: https://docs.google.com/spreadsheets/d/19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I/edit
// Configure the constants below before first run.
const SPREADSHEET_ID = '19yP3MfbDZe9DW9P4WM2VHI_zi6RBDweVRGOOAr6Vo8I';
const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const DATASET_ID = 'GSO'; // Change to your target dataset
const TABLE_ID = 'VerificationDisputeList';
const SHEET_NAME = 'DisputeList'; // Change if your sheet tab has a different name
// Composite key - using multiple columns to identify unique disputes
const KEY_COLUMNS = ['is_id', 'invoice_number', 'line']; // IS ID + Invoice + Line# uniquely identifies a dispute

// Main entry: run manually or from a trigger
function importDisputeLogToBigQuery() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    console.error('Sheet "' + SHEET_NAME + '" not found');
    return;
  }

  const dataRange = sheet.getDataRange();
  const values = dataRange.getValues();
  const displayValues = dataRange.getDisplayValues();
  if (!values || values.length < 2) {
    console.log('No data rows found (need header + at least one data row).');
    return;
  }

  const headersRaw = values[0].map(String);
  const headers = headersRaw.map(sanitizeHeader);
  const schemaFields = buildDisputeSchemaFields(headersRaw, headers);
  
  // Log the header mapping for debugging
  console.log('Header mapping:');
  for (let i = 0; i < headersRaw.length; i++) {
    console.log('  "' + headersRaw[i] + '" → "' + headers[i] + '"');
  }

  // Ensure target table exists with proper schema
  ensureDisputeTableExists(schemaFields);

  // Build row objects with intelligent parsing
  const rows = [];
  const parseErrors = [];
  
  for (let r = 1; r < values.length; r++) {
    const rowVals = values[r];
    const displayRowVals = displayValues[r];
    
    // Skip completely empty rows
    if (rowVals.every(c => c === '' || c === null || typeof c === 'undefined')) continue;
    
    // Check if all key columns are empty - if so, skip
    const isIdIdx = headersRaw.findIndex(h => h.toLowerCase().includes('is id'));
    if (isIdIdx >= 0 && !rowVals[isIdIdx]) continue;
    
    try {
      const obj = parseDisputeRow(headersRaw, headers, rowVals, displayRowVals, r + 1);
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
  createDisputeTempTable(tempTableId, schemaFields);

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
    const mergeSql = buildDisputeMergeSql(tempTableId, schemaFields);
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
function parseDisputeRow(headersRaw, headers, rowVals, displayRowVals, rowNum) {
  const obj = {};
  
  for (let c = 0; c < headers.length; c++) {
    const fieldName = headers[c];
    const rawValue = rowVals[c];
    const displayValue = displayRowVals && displayRowVals[c];
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
        obj[fieldName] = parseNumeric(rawValue, displayValue);
      }
      // STRING FIELDS - everything else
      else {
        obj[fieldName] = cleanString(displayValue !== '' ? displayValue : rawValue);
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
function parseNumeric(val, displayVal) {
  if (val === null || val === undefined || val === '') return null;
  
  let num;
  if (typeof val === 'number') {
    num = val;
  } else if (val instanceof Date) {
    const displayStr = String(displayVal || '').trim();
    if (!displayStr) return null;

    const parsedDisplay = parseFloat(displayStr.replace(/[$€£¥,\s]/g, ''));
    if (isNaN(parsedDisplay)) {
      console.warn('Numeric column contains date-formatted value with non-numeric display: "' + displayStr + '"');
      return null;
    }
    num = parsedDisplay;
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
function ensureDisputeTableExists(schemaFields) {
  let table;
  try {
    table = BigQuery.Tables.get(PROJECT_ID, DATASET_ID, TABLE_ID);
    console.log('Table ' + TABLE_ID + ' already exists.');
  } catch (e) {
    if (!isNotFoundError(e)) throw e;
  }

  if (!table) {
    console.log('Creating table ' + TABLE_ID + '...');
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
    return;
  }

  ensureTableHasColumns(table, schemaFields);
}

// Define the BigQuery schema for dispute log based on current sheet headers
function buildDisputeSchemaFields(headersRaw, headers) {
  const schemaFields = [];
  const seen = {};

  for (let i = 0; i < headers.length; i++) {
    const fieldName = headers[i];
    if (seen[fieldName]) continue;
    seen[fieldName] = true;

    schemaFields.push({
      name: fieldName,
      type: inferFieldType(headersRaw[i]),
      mode: 'NULLABLE'
    });
  }

  schemaFields.push({ name: '_source_row_number', type: 'STRING', mode: 'NULLABLE' });
  schemaFields.push({ name: 'ingestion_time', type: 'TIMESTAMP', mode: 'NULLABLE' });

  return schemaFields;
}

// Create temp table with same schema as main table
function createDisputeTempTable(tempTableId, schemaFields) {
  const tempSchemaFields = schemaFields.slice();
  // Add _load_uuid to temp table
  tempSchemaFields.push({ name: '_load_uuid', type: 'STRING', mode: 'NULLABLE' });
  
  const tableResource = {
    tableReference: {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      tableId: tempTableId
    },
    schema: { fields: tempSchemaFields }
  };
  
  BigQuery.Tables.insert(tableResource, PROJECT_ID, DATASET_ID);
  console.log('Created temp table ' + tempTableId);
}

// Build MERGE SQL with composite key
function buildDisputeMergeSql(tempTableId, schemaFields) {
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
  const updateCols = schemaFields
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

function inferFieldType(headerRaw) {
  const header = String(headerRaw || '').toLowerCase();
  if (header.includes('date')) return 'DATE';
  if (header.includes('amount') ||
      header.includes('exchange rate') ||
      header.includes('line #') ||
      header.includes('days of')) {
    return 'NUMERIC';
  }
  return 'STRING';
}

function ensureTableHasColumns(table, expectedFields) {
  const existingFields = (table.schema && table.schema.fields) ? table.schema.fields : [];
  const existingFieldNames = {};

  for (let i = 0; i < existingFields.length; i++) {
    existingFieldNames[existingFields[i].name] = true;
  }

  const missingFields = expectedFields.filter(function(field) {
    return !existingFieldNames[field.name];
  });

  if (missingFields.length === 0) return;

  const targetFqn = '`' + PROJECT_ID + '.' + DATASET_ID + '.' + TABLE_ID + '`';
  const addClauses = missingFields.map(function(field) {
    return 'ADD COLUMN IF NOT EXISTS ' + field.name + ' ' + field.type;
  }).join(', ');
  const sql = 'ALTER TABLE ' + targetFqn + ' ' + addClauses;
  const jobId = runQueryJob(sql);
  waitForJob(PROJECT_ID, jobId, 120000);

  console.log('Added missing columns to ' + TABLE_ID + ': ' + missingFields.map(function(field) {
    return field.name;
  }).join(', '));
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
