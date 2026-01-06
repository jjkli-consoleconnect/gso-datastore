/**
 * Infer schema fields from a sample row (object with header keys)
 */
function deriveSchemaFromSample(headers, sampleRow) {
  if (!headers || !Array.isArray(headers)) return [];
  const fields = [];
  for (let i = 0; i < headers.length; i++) {
    const name = headers[i] || ('col_' + i);
    const val = sampleRow && sampleRow[name];
    let type = 'STRING';
    if (val instanceof Date) type = 'DATE';
    fields.push({ name: name, type: type });
  }
  return fields;
}

// Toggle verbose troubleshooting logs. Set to true only when actively debugging.
const DEBUG = true;

/**
 * Main function to process new Excel files uploaded to the Drive folder.
 * This function checks for new .xlsx files since the last run and processes them.
 */
function processNewFiles() {
  // Single source folder contains both "all expired" and "to-be-expired" files
  const folderId = '1Vt2f01EYAk2e-8-_gV55VlAoU4Uysyn5';
  const folder = DriveApp.getFolderById(folderId);

  // Get the timestamp of the last processed file
  const scriptProperties = PropertiesService.getScriptProperties();
  const lastProcessed = parseInt(scriptProperties.getProperty('lastProcessed')) || 0;

  const files = folder.getFiles();
  const runStart = new Date();
  const lastProcessedIso = lastProcessed ? new Date(lastProcessed).toISOString() : 'never';
  if (DEBUG) Logger.log('CostItemExpiration run started at ' + runStart.toISOString() + ' with lastProcessed=' + lastProcessedIso);

  // Patterns: flexible to accept variations in filename prefixes for safety (weekly optional, all_ optional for expired)
  const patternAll = /^weekly_?(all_)?expired.*_(\d{4}-\d{2}-\d{2})\.xlsx$/i;
  const patternToBe = /^weekly_?to_be_expired.*_(\d{4}-\d{2}-\d{2})\.xlsx$/i;

  const candidatesAll = [];
  const candidatesToBe = [];
  let processedNewestTimestamp = lastProcessed;
  let scannedCount = 0;

  while (files.hasNext()) {
    const file = files.next();
    scannedCount++;
    const fileName = file.getName();
    const mime = file.getMimeType();
    if (mime !== 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') continue;

    const created = file.getDateCreated && file.getDateCreated();
    const updated = file.getLastUpdated && file.getLastUpdated();
    const createdTime = created ? created.getTime() : 0;
    const updatedTime = updated ? updated.getTime() : 0;
    const effectiveTimestamp = Math.max(createdTime, updatedTime);
    const effectiveIso = effectiveTimestamp ? new Date(effectiveTimestamp).toISOString() : 'unknown';

    Logger.log('Scanned file: ' + fileName + ' effective=' + effectiveIso);

    // Check 'all' pattern
    let m = fileName.match(patternAll);
    if (m) {
      const dateStr = m[2]; // m[1] is (all_)? group, m[2] is the date
      const fileNameDate = new Date(dateStr).getTime();
      if (fileNameDate <= lastProcessed) {
        Logger.log('Skipping ALL file (filename date <= lastProcessed): ' + fileName + ' fileDate=' + dateStr + ' lastProcessed=' + lastProcessedIso + ' diff=' + (fileNameDate - lastProcessed));
      } else {
        Logger.log('Queueing ALL file: ' + fileName + ' fileDate=' + dateStr);
        candidatesAll.push({ file: file, name: fileName, date: dateStr, timestamp: effectiveTimestamp });
        if (effectiveTimestamp > processedNewestTimestamp) processedNewestTimestamp = effectiveTimestamp;
      }
      continue;
    }

    // Check 'to-be-expired' pattern
    m = fileName.match(patternToBe);
    if (m) {
      const dateStr = m[1];
      const fileNameDate = new Date(dateStr).getTime();
      if (fileNameDate <= lastProcessed) {
        Logger.log('Skipping TO-BE file (filename date <= lastProcessed): ' + fileName + ' fileDate=' + dateStr + ' lastProcessed=' + lastProcessedIso + ' diff=' + (fileNameDate - lastProcessed));
      } else {
        if (DEBUG) Logger.log('Queueing TO-BE file: ' + fileName + ' fileDate=' + dateStr);
        candidatesToBe.push({ file: file, name: fileName, date: dateStr, timestamp: effectiveTimestamp });
        if (effectiveTimestamp > processedNewestTimestamp) processedNewestTimestamp = effectiveTimestamp;
      }
      continue;
    }
  }

  if (DEBUG) Logger.log('Scanned ' + scannedCount + ' total file(s) in source folder.');

  // For 'all' expired, pick the single latest (newest) file by the date in the filename (not metadata)
  let latestAll = null;
  let latestAllDate = null;
  candidatesAll.forEach(c => {
    const d = new Date(c.date);
    if (!latestAllDate || d > latestAllDate) {
      latestAllDate = d;
      latestAll = c;
    }
  });

  const selectedAllFiles = latestAll ? [latestAll.file] : [];

  // For to-be-expired, pick the single latest (newest) file by the date in the filename (not metadata)
  let latestToBe = null;
  let latestToBeDate = null;
  candidatesToBe.forEach(c => {
    const d = new Date(c.date);
    if (!latestToBeDate || d > latestToBeDate) {
      latestToBeDate = d;
      latestToBe = c;
    }
  });

  Logger.log('Processing ' + selectedAllFiles.length + ' ALL file; TO-BE present=' + (latestToBe ? 'yes' : 'no'));
  if (selectedAllFiles.length > 0) Logger.log('Selected ALL file: ' + selectedAllFiles[0].getName());
  if (latestToBe) Logger.log('Selected TO-BE file: ' + latestToBe.file.getName());

  // Process ALL files as a single staging + MERGE
  if (selectedAllFiles.length > 0) {
    try {
      processAndMergeFiles(selectedAllFiles, 'expired_cost_items');
    } catch (e) {
      Logger.log('Error during ALL files merge: ' + e.message);
    }
  }

  // Process latest TO-BE file (single file): replace previous To-be-Expired rows
  if (latestToBe) {
    try {
      processAndMergeToBeExpired(latestToBe.file, 'expired_cost_items');
    } catch (e) {
      Logger.log('Error during TO-BE processing: ' + e.message);
    }
  }

  // Update last processed timestamp
  if (selectedAllFiles.length > 0 || latestToBe) {
    processedNewestTimestamp = Math.max(processedNewestTimestamp, runStart.getTime());
    scriptProperties.setProperty('lastProcessed', processedNewestTimestamp.toString());
    if (DEBUG) Logger.log('Updated lastProcessed to ' + new Date(processedNewestTimestamp).toISOString());
  } else {
    if (DEBUG) Logger.log('No new files were processed; lastProcessed remains at ' + lastProcessedIso);
  }
}

/**
 * Processes a single Excel file: converts to sheet, reads data, and inserts into BigQuery.
 * @param {File} file - The Drive file object.
 */
function processFile(file) {
  // Convert Excel to Google Sheet using Drive API with retries and support for shared drives
  const fileId = file.getId();
  Logger.log('Processing file: ' + file.getName() + ' id=' + fileId + ' lastUpdated=' + file.getLastUpdated());

  const copyRequest = {
    title: 'Temp Converted Sheet - ' + file.getName(),
    mimeType: 'application/vnd.google-apps.spreadsheet'
  };

  // Try copy up to 3 times with backoff
  let convertedFile = null;
  let attempt = 0;
  while (attempt < 3 && !convertedFile) {
    attempt++;
    try {
      // supportsAllDrives:true handles files on shared drives
      convertedFile = Drive.Files.copy(copyRequest, fileId, {supportsAllDrives: true});
      Logger.log('Drive.Files.copy succeeded on attempt ' + attempt + ' -> id=' + convertedFile.id);
    } catch (e) {
      Logger.log('Drive.Files.copy attempt ' + attempt + ' failed: ' + e.message);
      // If it's a transient server error, wait and retry
      Utilities.sleep(2000 * attempt);
    }
  }

  if (!convertedFile) {
    throw new Error('Failed to convert file to Google Sheet after retries: ' + file.getName());
  }

  // Give Drive a short moment to finalize the conversion
  Utilities.sleep(3000);

  // Open the converted file via DriveApp (safer for Apps Script)
  const convertedDriveFile = DriveApp.getFileById(convertedFile.id);
  const spreadsheet = SpreadsheetApp.open(convertedDriveFile);

  // Assume data is in the first sheet
  const sheet = spreadsheet.getSheets()[0];
  const data = sheet.getDataRange().getValues();
  if (!data || data.length < 2) {
    Logger.log('No data rows found in spreadsheet: ' + file.getName());
    try { DriveApp.getFileById(convertedFile.id).setTrashed(true); } catch (e) {}
    return;
  }

  // Header-driven mapping: first row are headers
  const headers = data[0].map(h => sanitizeHeader(String(h || '').trim()));
  const rows = data.slice(1);

  // Ensure BigQuery table exists and has columns for headers (try to infer types from first non-empty row)
  const sampleRow = rows.find(r => r && r.length > 0) || rows[0];
  const inferredSchema = deriveSchemaFromSample(headers, sampleRow);
  ensureTableSchema('pccw-internal-virt-agent-uat', 'CostItemExpiration', 'expired_cost_items', inferredSchema);

  // Build JSON rows keyed by header names
  const jsonRows = rows.map(r => {
    const obj = {};
    headers.forEach((h, i) => {
      let v = r[i];
      if (v instanceof Date) v = v.toISOString().split('T')[0];
      if (v === '' || v === undefined) v = null;
      obj[h] = v;
    });
    return { json: obj };
  });

  // Insert into BigQuery
  try {
    BigQuery.Tabledata.insertAll({ rows: jsonRows }, 'pccw-internal-virt-agent-uat', 'CostItemExpiration', 'expired_cost_items');
    Logger.log('Inserted ' + jsonRows.length + ' rows into expired_cost_items');
  } catch (e) {
    Logger.log('BigQuery insertAll failed: ' + e.message);
    throw e;
  }

  // Clean up temporary file
  try { DriveApp.getFileById(convertedFile.id).setTrashed(true); } catch (e) { Logger.log('Failed to trash converted file: ' + e.message); }
}

/**
 * Normalize header into BigQuery-friendly column name
 */
function sanitizeHeader(h) {
  // normalize to lowercase_snake_case
  return String(h || '')
    .trim()
    .replace(/\s+/g, '_')               // spaces -> underscore
    .replace(/[^A-Za-z0-9_]/g, '')       // remove other chars
    .replace(/__+/g, '_')                // collapse double underscores
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
}

/**
 * Process multiple files into a staging table and MERGE into the target table.
 * files: array of Drive File objects
 * targetTableId: string (table name)
 */
function processAndMergeFiles(files, targetTableId) {
  const projectId = 'pccw-internal-virt-agent-uat';
  const datasetId = 'CostItemExpiration';

  // We'll create a single staging table name unique by timestamp
  const stagingTable = 'staging_' + new Date().getTime();

  // We'll collect headers from the first file processed and reuse for all files (assume consistent schema)
  let commonHeaders = null;
  const allJsonRows = [];

  files.forEach(file => {
    Logger.log('Preparing file for staging: ' + file.getName());
    const converted = convertExcelToSheet(file);
    const sheet = SpreadsheetApp.open(DriveApp.getFileById(converted.id)).getSheets()[0];
    const data = sheet.getDataRange().getValues();
    DriveApp.getFileById(converted.id).setTrashed(true);
    if (!data || data.length < 2) return;
    const headers = data[0].map(h => sanitizeHeader(String(h || '').trim()));
    if (!commonHeaders) commonHeaders = headers;
    // Ensure headers align; if not, fill missing columns with null for that row
    const rows = data.slice(1);
    rows.forEach(r => {
      const obj = {};
      // Map file headers to values
      const fileHeaderMap = {};
      headers.forEach((h, i) => {
        fileHeaderMap[h] = r[i];
      });
      // Use commonHeaders and fill missing with null
      commonHeaders.forEach((h, i) => {
        let v = fileHeaderMap[h];
        // Parse date strings (e.g., '1/12/2025' or '7/12/2016') to YYYY-MM-DD
        if (typeof v === 'string' && /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(v)) {
          const parts = v.split('/');
          if (parts.length === 3) {
            const day = parseInt(parts[0], 10);
            const month = parseInt(parts[1], 10) - 1; // JS months are 0-based
            const year = parseInt(parts[2], 10);
            const date = new Date(year, month, day);
            if (!isNaN(date.getTime())) {
              v = date.toISOString().split('T')[0];
            }
          }
        } else if (v instanceof Date) {
          v = v.toISOString().split('T')[0];
        }
        obj[h] = (v === '' || v === undefined) ? null : v;
      });
      // If expire_type column is missing, infer from filename (all files are 'Expired')
      if (!obj.hasOwnProperty('expire_type')) obj.expire_type = 'Expired';
      allJsonRows.push({ json: obj });
    });
  });

  // Add all possible columns from to-be-expired schema that expired files don't have
  const extraColumns = ['expire_type', 'salesrecord', 'gcid', 'sequence', 'rateusd', 'receivingyear', 'reqdetailid', 
                        'cost_type_desc', 'rpttype', 'next_br', 'next_brstatus', 'next_brsubmitdate', 'next_brapprovalinfo',
                        'next_pr', 'next_prstatus', 'next_prsubmitdate', 'next_prverifyinfo', 'next_prapprovalinfo',
                        'vendormanager', 'vendormanageremail', 'next_ct', 'next_ctstatus', 'org_costitemid', 
                        'org_costitemcreatedate', 'this_costitemcreatedate', 'expired_calendar_months', 'estimated_accrual_usd'];
  
  extraColumns.forEach(col => {
    if (commonHeaders && commonHeaders.indexOf(col) === -1) {
      commonHeaders.push(col);
      // Fill all existing rows with null for this column
      allJsonRows.forEach(row => {
        if (!row.json.hasOwnProperty(col)) {
          row.json[col] = null;
        }
      });
    }
  });

  if (!commonHeaders || allJsonRows.length === 0) {
    Logger.log('No rows found to stage.');
    return;
  }

  // Create staging table with schema derived from commonHeaders and sample row types
  const sampleRow = allJsonRows.find(r => r && r.json) && allJsonRows.find(r => r && r.json).json;
  const schemaFields = commonHeaders.map(h => {
    const v = sampleRow[h];
    let type = 'STRING';
    // Force certain columns to always be STRING to avoid type conflicts
    const lowerH = h.toLowerCase();
    if (lowerH === 'org_costitemid' || lowerH === 'org_costitemcreatedate') {
      type = 'STRING';
    } else if (v && /^\d{4}-\d{2}-\d{2}$/.test(String(v))) {
      type = 'DATE';
    } else if (typeof v === 'number') {
      type = 'FLOAT64';
    }
    return { name: h, type: type };
  });

  createStagingTable(projectId, datasetId, stagingTable, schemaFields);

  // Insert rows into staging in batches of 500
  insertJsonRowsToTable(projectId, datasetId, stagingTable, allJsonRows);

  // Debug: log staging info
  try {
    debugLogStaging(projectId, datasetId, stagingTable, 'ALL', commonHeaders, allJsonRows);
  } catch (e) {
    Logger.log('debugLogStaging failed: ' + e.message);
  }

  // Run MERGE: assume primary key is costitemid (case-insensitive)
  runMergeFromStaging(projectId, datasetId, stagingTable, targetTableId, 'costitemid');

  // Drop staging
  dropTableIfExists(projectId, datasetId, stagingTable);
  Logger.log('Merge completed for ALL files.');
}

/**
 * Process the latest to-be-expired file: stage and then run a MERGE that effectively replaces rows
 * where expire_type = 'To-be-Expired'. We'll stage the file (setting expire_type for all rows based on filename)
 * and then delete existing To-be-Expired rows via MERGE semantics (update/delete) and insert the new ones.
 */
function processAndMergeToBeExpired(file, targetTableId) {
  const projectId = 'pccw-internal-virt-agent-uat';
  const datasetId = 'CostItemExpiration';
  const stagingTable = 'staging_tobe_' + new Date().getTime();

  const converted = convertExcelToSheet(file);
  const sheet = SpreadsheetApp.open(DriveApp.getFileById(converted.id)).getSheets()[0];
  const data = sheet.getDataRange().getValues();
  DriveApp.getFileById(converted.id).setTrashed(true);
  if (!data || data.length < 2) {
    Logger.log('No data in to-be file: ' + file.getName());
    return;
  }

  const headers = data[0].map(h => sanitizeHeader(String(h || '').trim()));
  const rows = data.slice(1);
  const jsonRows = rows.map(r => {
    const obj = {};
    headers.forEach((h, i) => {
      let v = r[i];
      // Parse date strings (e.g., '1/12/2025' or '7/12/2016') to YYYY-MM-DD
      if (typeof v === 'string' && /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(v)) {
        const parts = v.split('/');
        if (parts.length === 3) {
          const day = parseInt(parts[0], 10);
          const month = parseInt(parts[1], 10) - 1; // JS months are 0-based
          const year = parseInt(parts[2], 10);
          const date = new Date(year, month, day);
          if (!isNaN(date.getTime())) {
            v = date.toISOString().split('T')[0];
          }
        }
      } else if (v instanceof Date) {
        v = v.toISOString().split('T')[0];
      }
      obj[h] = (v === '' || v === undefined) ? null : v;
    });
    // Set expire_type based on filename (to-be files are 'To-be-Expired')
    obj.expire_type = 'To-be-Expired';
    return { json: obj };
  });

  if (jsonRows.length === 0) {
    Logger.log('No rows in to-be file: ' + file.getName());
    return;
  }

  // Create staging with inferred schema
  const sampleRow = jsonRows[0].json;
  const schemaFields = Object.keys(sampleRow).map(k => {
    const v = sampleRow[k];
    let type = 'STRING';
    // Force certain columns to always be STRING to avoid type conflicts
    const lowerK = k.toLowerCase();
    if (lowerK === 'org_costitemid' || lowerK === 'org_costitemcreatedate') {
      type = 'STRING';
    } else if (v && /^\d{4}-\d{2}-\d{2}$/.test(String(v))) {
      type = 'DATE';
    } else if (typeof v === 'number') {
      type = 'FLOAT64';
    }
    return { name: k, type: type };
  });

  createStagingTable(projectId, datasetId, stagingTable, schemaFields);
  insertJsonRowsToTable(projectId, datasetId, stagingTable, jsonRows);

  // Debug: log staging info for to-be
  try {
    debugLogStaging(projectId, datasetId, stagingTable, 'TO-BE', Object.keys(sampleRow), jsonRows);
  } catch (e) {
    Logger.log('debugLogStaging failed: ' + e.message);
  }

  // MERGE logic: remove existing To-be-Expired rows and insert new ones.
  // We'll match on costitemid if present; otherwise rely on full row deduping by all columns.
  runMergeFromStaging(projectId, datasetId, stagingTable, targetTableId, 'costitemid', "Expire_type = 'To-be-Expired'");

  dropTableIfExists(projectId, datasetId, stagingTable);
  Logger.log('To-be-Expired merge completed.');
}

/**
 * Convert Excel file to Google Sheet using Drive API (reuse existing logic)
 */
function convertExcelToSheet(file) {
  const fileId = file.getId();
  const copyRequest = { title: 'Temp Converted Sheet - ' + file.getName(), mimeType: 'application/vnd.google-apps.spreadsheet' };
  let convertedFile = null;
  let attempt = 0;
  while (attempt < 3 && !convertedFile) {
    attempt++;
    try {
      convertedFile = Drive.Files.copy(copyRequest, fileId, { supportsAllDrives: true });
      Logger.log('Drive.Files.copy succeeded on attempt ' + attempt + ' -> id=' + convertedFile.id);
    } catch (e) {
      Logger.log('Drive.Files.copy attempt ' + attempt + ' failed: ' + e.message);
      Utilities.sleep(2000 * attempt);
    }
  }
  if (!convertedFile) throw new Error('Failed to convert file to Google Sheet: ' + file.getName());
  Utilities.sleep(2000);
  return convertedFile;
}

/**
 * Create a staging table with provided schema fields.
 */
function createStagingTable(projectId, datasetId, tableId, fields) {
  const resource = {
    tableReference: { projectId: projectId, datasetId: datasetId, tableId: tableId },
    schema: { fields: fields }
  };
  try {
    BigQuery.Tables.insert(resource, projectId, datasetId);
    Logger.log('Created staging table: ' + tableId);
    // Wait until table is visible/ready before inserting rows
    try {
      waitForTableReady(projectId, datasetId, tableId, 30); // wait up to 30s
    } catch (e) {
      Logger.log('waitForTableReady failed: ' + e.message);
      // proceed anyway; inserts may still succeed but could be caught by later checks
    }
  } catch (e) {
    Logger.log('Failed to create staging table: ' + e.message);
    throw e;
  }
}

/**
 * Wait for a BigQuery table to become available. Polls BigQuery.Tables.get until it succeeds and has a schema.
 * timeoutSeconds: how long to wait before throwing
 */
function waitForTableReady(projectId, datasetId, tableId, timeoutSeconds) {
  const start = new Date().getTime();
  const timeout = (timeoutSeconds || 30) * 1000;
  while (true) {
    try {
      const t = BigQuery.Tables.get(projectId, datasetId, tableId);
      if (t && t.schema && Array.isArray(t.schema.fields)) {
        Logger.log('Table ready: ' + tableId + ' with ' + t.schema.fields.length + ' fields');
        return;
      }
    } catch (e) {
      // continue polling
    }
    if (new Date().getTime() - start > timeout) {
      throw new Error('Timeout waiting for table ready: ' + tableId);
    }
    Utilities.sleep(1000);
  }
}

/**
 * Insert JSON rows into a table in batches.
 */
function insertJsonRowsToTable(projectId, datasetId, tableId, jsonRows) {
  const batchSize = 500;
  for (let i = 0; i < jsonRows.length; i += batchSize) {
    const batch = jsonRows.slice(i, i + batchSize);
    try {
      const res = BigQuery.Tabledata.insertAll({ rows: batch }, projectId, datasetId, tableId);
      // Check for insertErrors in the response
      if (res && res.insertErrors && res.insertErrors.length > 0) {
        Logger.log('insertAll reported errors for ' + tableId + ': ' + JSON.stringify(res.insertErrors.slice(0,5)));
        throw new Error('BigQuery insertAll returned insertErrors (see logs)');
      }
      Logger.log('Inserted batch of ' + batch.length + ' rows into ' + tableId);
    } catch (e) {
      Logger.log('Failed to insert batch into ' + tableId + ': ' + e.message + '\nBatch sample: ' + JSON.stringify(batch.slice(0,2)));
      throw e;
    }
  }
}

/**
 * Run a MERGE from staging to target using BigQuery SQL. mergeKey is the column name in lower_snake_case.
 * optionalWhere is an additional WHERE clause to target only specific rows (e.g. Expire_type = 'To-be-Expired')
 */
function runMergeFromStaging(projectId, datasetId, stagingTable, targetTable, mergeKey, optionalWhere) {
  // Query staging and target schema
  const stagingInfo = BigQuery.Tables.get(projectId, datasetId, stagingTable);
  const stagingFields = (stagingInfo.schema && stagingInfo.schema.fields) || [];
  // Ensure target has required schema before merge
  try {
    ensureTableSchema(projectId, datasetId, targetTable, stagingFields);
  } catch (e) {
    Logger.log('Failed to ensure target schema before merge: ' + e.message);
    throw e;
  }
  const targetInfo = BigQuery.Tables.get(projectId, datasetId, targetTable);
  const targetFields = (targetInfo && targetInfo.schema && targetInfo.schema.fields) || [];
  const targetTypeMap = {};
  targetFields.forEach(f => { targetTypeMap[String(f.name).toLowerCase()] = normalizeBqType(f.type || 'STRING'); });

  const colsList = stagingFields.map(f => `\`${f.name}\``).join(', ');

  // Build ON clause
  let onClause;
  if (mergeKey && stagingFields.some(f => f.name.toLowerCase() === mergeKey.toLowerCase())) {
    onClause = `T.${mergeKey} = S.${mergeKey}`;
    // Special case for expired_cost_items: include snapshot_date in ON clause to handle multiple snapshots per costitemid
    if (targetTable.toLowerCase() === 'expired_cost_items' && mergeKey.toLowerCase() === 'costitemid' && stagingFields.some(f => f.name.toLowerCase() === 'snapshot_date')) {
      onClause += ` AND T.snapshot_date = S.snapshot_date`;
    }
  } else {
    const pairs = stagingFields.map(f => `COALESCE(CAST(T.${f.name} AS STRING),'') = COALESCE(CAST(S.${f.name} AS STRING),'')`);
    onClause = pairs.join(' AND ');
  }

  // Build update assignments with SAFE_CAST to the target type
  const updateAssignments = stagingFields.map(f => {
    const tname = f.name;
    const targetType = targetTypeMap[tname.toLowerCase()] || 'STRING';
    if (targetType === 'STRING') return `T.${tname} = S.${tname}`;
    return `T.${tname} = SAFE_CAST(S.${tname} AS ${targetType})`;
  }).join(', ');

  const insertValues = stagingFields.map(f => {
    const tname = f.name;
    const targetType = targetTypeMap[tname.toLowerCase()] || 'STRING';
    if (targetType === 'STRING') return `S.${tname}`;
    return `SAFE_CAST(S.${tname} AS ${targetType})`;
  }).join(', ');

  // If optionalWhere is provided, use a subquery to filter staging rows; otherwise deduplicate to avoid MERGE conflicts
  let usingClause = `\`${projectId}.${datasetId}.${stagingTable}\` S`;
  if (optionalWhere) {
    usingClause = `(SELECT * FROM \`${projectId}.${datasetId}.${stagingTable}\` WHERE ${optionalWhere}) S`;
  } else {
    // Deduplicate staging table on merge keys to prevent multiple source rows matching one target row
    // Check if both costitemid and snapshot_date exist in staging
    const hasCostItemId = stagingFields.some(f => f.name.toLowerCase() === 'costitemid');
    const hasSnapshotDate = stagingFields.some(f => f.name.toLowerCase() === 'snapshot_date');
    if (hasCostItemId && hasSnapshotDate) {
      usingClause = `(SELECT * FROM \`${projectId}.${datasetId}.${stagingTable}\` QUALIFY ROW_NUMBER() OVER (PARTITION BY CAST(costitemid AS STRING), CAST(snapshot_date AS STRING) ORDER BY costitemid) = 1) S`;
    } else if (hasCostItemId) {
      usingClause = `(SELECT * FROM \`${projectId}.${datasetId}.${stagingTable}\` QUALIFY ROW_NUMBER() OVER (PARTITION BY CAST(costitemid AS STRING) ORDER BY costitemid) = 1) S`;
    }
    // else use table directly without deduplication
  }

  const mergeSql = `MERGE \`${projectId}.${datasetId}.${targetTable}\` T
USING ${usingClause}
ON (${onClause})
WHEN MATCHED THEN
  UPDATE SET ${updateAssignments}
WHEN NOT MATCHED THEN
  INSERT (${colsList})
  VALUES (${insertValues});`;

  Logger.log('Running MERGE SQL...');
  // Debug: log the MERGE SQL for inspection
  try { Logger.log('MERGE SQL:\n' + mergeSql); } catch (e) { Logger.log('Failed to log MERGE SQL: ' + e.message); }
  const job = BigQuery.Jobs.insert({ configuration: { query: { query: mergeSql, useLegacySql: false } } }, projectId);
  const jobId = job.jobReference.jobId;
  for (let i = 0; i < 60; i++) {
    const status = BigQuery.Jobs.get(projectId, jobId).status;
    if (status && status.state === 'DONE') {
      if (status.errorResult) throw new Error('Merge job failed: ' + JSON.stringify(status.errorResult));
      Logger.log('Merge job completed.');
      // Fetch job again to get statistics
      try {
        const finished = BigQuery.Jobs.get(projectId, jobId);
        const stats = finished.statistics || {};
        Logger.log('Merge job statistics: ' + JSON.stringify(stats));
        // If query statistics available, try to log rows affected
        if (stats && stats.query) {
          Logger.log('Query statistics: statementType=' + stats.query.statementType + ' totalBytesProcessed=' + stats.query.totalBytesProcessed);
          if (stats.query && stats.query.totalRowsProcessed !== undefined) {
            Logger.log('Query totalRowsProcessed=' + stats.query.totalRowsProcessed);
          }
        }
        if (finished.statistics && finished.statistics.dmlStats) {
          Logger.log('DML stats: ' + JSON.stringify(finished.statistics.dmlStats));
        }
      } catch (e) {
        Logger.log('Failed to fetch merge job statistics: ' + e.message);
      }
      return;
    }
    Utilities.sleep(1000 * (i + 1));
  }
  throw new Error('Merge job did not complete in time.');
}

/**
 * Drop a table if it exists.
 */
function dropTableIfExists(projectId, datasetId, tableId) {
  try {
    BigQuery.Tables.remove(projectId, datasetId, tableId);
    Logger.log('Dropped table: ' + tableId);
  } catch (e) {
    if (e && e.message && e.message.indexOf('Not found') !== -1) {
      Logger.log('Table not found (no need to drop): ' + tableId);
    } else {
      Logger.log('Error dropping table ' + tableId + ': ' + e.message);
    }
  }
}

/**
 * Debug helper: log basic staging table info (row count, sample rows, null mergeKey count)
 */
function debugLogStaging(projectId, datasetId, tableId, tag, headers, jsonRows) {
  if (!DEBUG) return;
  try {
    Logger.log('DEBUG[' + tag + '] Staging table: ' + projectId + '.' + datasetId + '.' + tableId);
    // Count rows via Tabledata.list (fast for small staging tables); fall back to provided jsonRows length
    let count = 0;
    try {
      // Tabledata.list returns up to 100,000 rows; we only need counts/sample
      const res = BigQuery.Tabledata.list(projectId, datasetId, tableId);
      if (res && res.totalRows !== undefined) {
        count = Number(res.totalRows);
      } else if (Array.isArray(jsonRows)) {
        count = jsonRows.length;
      }
    } catch (e) {
      count = Array.isArray(jsonRows) ? jsonRows.length : 0;
    }
    Logger.log('DEBUG[' + tag + '] Staging rowCount=' + count);

    // Sample up to 3 rows from jsonRows if available
    if (Array.isArray(jsonRows) && jsonRows.length > 0) {
      const samples = jsonRows.slice(0, 3).map(r => r.json || r);
      Logger.log('DEBUG[' + tag + '] sampleRows=' + JSON.stringify(samples));
    }

    // If merge key present, count null/empty occurrences in the provided jsonRows (best-effort)
    if (mergeKeyCandidate(headers)) {
      const mk = mergeKeyCandidate(headers);
      const nulls = (Array.isArray(jsonRows) ? jsonRows : []).reduce((acc, r) => {
        const v = (r.json || r)[mk];
        return acc + ((v === null || v === undefined || String(v).trim() === '') ? 1 : 0);
      }, 0);
      Logger.log('DEBUG[' + tag + '] mergeKeyCandidate=' + mk + ' nullOrEmptyCount=' + nulls + ' of ' + (Array.isArray(jsonRows) ? jsonRows.length : 0));
    } else {
      Logger.log('DEBUG[' + tag + '] no mergeKeyCandidate found in headers');
    }
  } catch (e) {
    Logger.log('debugLogStaging top-level failure: ' + e.message);
  }
}

function mergeKeyCandidate(headers) {
  if (!headers || !Array.isArray(headers)) return null;
  const lower = headers.map(h => String(h).toLowerCase());
  if (lower.indexOf('costitemid') !== -1) return 'costitemid';
  if (lower.indexOf('cost_item_id') !== -1) return 'cost_item_id';
  if (lower.indexOf('costitem') !== -1) return 'costitem';
  return null;
}

/**
 * Normalize BigQuery type names to canonical values used by BigQuery SQL.
 */
function normalizeBqType(t) {
  if (!t) return 'STRING';
  const s = String(t).trim().toUpperCase();
  if (s === 'FLOAT' || s === 'DOUBLE') return 'FLOAT64';
  if (s === 'INT' || s === 'INTEGER') return 'INT64';
  if (s === 'BOOL' || s === 'BOOLEAN') return 'BOOL';
  if (s === 'STRING' || s === 'DATE' || s === 'TIMESTAMP') return s;
  // default fallback
  return s;
}

/**
 * Ensure BigQuery table exists and has the provided fields. Adds missing columns as STRING by default.
 */
function ensureTableSchema(projectId, datasetId, tableId, fields) {
  try {
    const table = BigQuery.Tables.get(projectId, datasetId, tableId);
    const existing = (table.schema && table.schema.fields) || [];
    const existingNames = existing.map(f => String(f.name).toLowerCase());
    const missing = fields.filter(f => existingNames.indexOf(String(f.name).toLowerCase()) === -1);
    if (missing.length === 0) return;
    // Add each missing column via ALTER TABLE
    missing.forEach(f => {
      const type = normalizeBqType(f.type || 'STRING');
      const alterSql = `ALTER TABLE \`${projectId}.${datasetId}.${tableId}\` ADD COLUMN ${f.name} ${type}`;
      Logger.log('Adding missing column: ' + f.name + ' as ' + type);
      const alterJob = BigQuery.Jobs.insert({ configuration: { query: { query: alterSql, useLegacySql: false } } }, projectId);
      const alterJobId = alterJob.jobReference.jobId;
      for (let j = 0; j < 20; j++) {
        const s = BigQuery.Jobs.get(projectId, alterJobId).status;
        if (s && s.state === 'DONE') {
          if (s.errorResult) throw new Error('BigQuery alter job failed: ' + JSON.stringify(s.errorResult));
          Logger.log('Added column ' + f.name);
          break;
        }
        Utilities.sleep(1000 * (j + 1));
      }
    });
  } catch (e) {
    // Table not found -> create it
    if (e && e.message && e.message.indexOf('Not found') !== -1) {
      Logger.log('Table not found; creating table ' + tableId);
      const resource = {
        tableReference: { projectId: projectId, datasetId: datasetId, tableId: tableId },
        schema: { fields: fields }
      };
      BigQuery.Tables.insert(resource, projectId, datasetId);
      Logger.log('Table created: ' + tableId);
      return;
    }
    throw e;
  }
}

/**
 * Inserts rows into BigQuery table.
 * @param {Array<Array>} rows - Array of row arrays.
 */
function insertToBigQuery(rows) {
  const projectId = 'pccw-internal-virt-agent-uat'; // From your BigQuery config
  const datasetId = 'CostItemExpiration'; // Dataset from your specification
  const tableId = 'expired_cost_items'; // Table to create/append to

  // Prepare rows for BigQuery streaming insert
  const insertRows = rows.map(row => ({
    json: {
      CostItemID: row[0] || null,
      SignedCompany: row[1] || '',
      VendorName: row[2] || '',
      VendorCode: row[3] || '',
      CostType: row[4] || '',
      VendorType: row[5] || '',
      ReachType: row[6] || '',
      GLCode: row[7] || '',
      CCC: row[8] || '',
      POType: row[9] || '',
      PONumber: row[10] || '',
      POLineNum: row[11] || null,
      LISPONum: row[12] || null,
      CostCategory: row[13] || '',
      CostSubCategory: row[14] || '',
      Nomenclature: row[15] || '',
      Description: row[16] || '',
      AEndAddress: row[17] || '',
      BEndAddress: row[18] || '',
      BillingType: row[19] || '',
      Currency: row[20] || '',
      Quantity: row[21] || null,
      UnitPrice: row[22] || null,
      UOM: row[23] || '',
      MRC: row[24] || null,
      MRC_USD: row[25] || null,
      StartBillingDate: row[26] ? new Date(row[26]).toISOString().split('T')[0] : null,
      StopBillingDate: row[27] ? new Date(row[27]).toISOString().split('T')[0] : null,
      ServiceHandoverDate: row[28] ? new Date(row[28]).toISOString().split('T')[0] : null,
      ReceivedQty: row[29] || null,
      ReveivedAmount: row[30] || null,
      ReceivingDate: row[31] ? new Date(row[31]).toISOString().split('T')[0] : null,
      CustomerName: row[32] || null,
      SRProductFamily: row[33] || null,
      SRProductType: row[34] || null,
      SalesRegion: row[35] || null,
      SignedBDMName: row[36] || null,
      SRStatus: row[37] || null,
      ProvisioningCentre: row[38] || null,
      Requester: row[39] || '',
      ProjectNumber: row[40] || '',
      TerminationNoticeDay: row[41] || null,
      ItemStatus: row[42] || '',
      PopID: row[43] || '',
      TerminationPriorSendingDay: row[44] || null,
      PRID: row[45] || null,
      PRItemID: row[46] || null,
      WONumber: row[47] || null,
      PCCWGServiceID: row[48] || '',
      VendorCircuitID: row[49] || '',
      PRRequesterGroup: row[50] || '',
      snapshot_date: row[51] ? new Date(row[51]).toISOString().split('T')[0] : null
    }
  }));

  const request = {
    rows: insertRows
  };

  try {
    BigQuery.Tabledata.insertAll(request, projectId, datasetId, tableId);
    Logger.log(`Inserted ${rows.length} rows into BigQuery.`);
  } catch (error) {
    Logger.log(`BigQuery insert error: ${error}`);
  }
}

/**
 * Manual trigger function for testing.
 */
function myFunction() {
  // Single entry point: processAll files and to-be-expired files are handled inside processNewFiles()
  processNewFiles();
}

/**
 * Process the latest "to-be-expired" file in a folder (based on date in filename).
 * - Finds the file named like weekly_to_be_expired_cost_item_YYYY-MM-DD.xlsx with the latest date
 * - Converts it to a Sheet, reads header-driven rows
 * - Deletes existing rows in BigQuery where Expire_type = 'To-be-Expired'
 * - Inserts the fresh rows
 */
function processLatestToBeExpiredFolder(folderId) {
  const folder = DriveApp.getFolderById(folderId);
  const files = folder.getFiles();
  const pattern = /^weekly_to_be_expired_cost_item_(\d{4}-\d{2}-\d{2})\.xlsx$/;

  let latest = null;
  let latestDate = null;

  while (files.hasNext()) {
    const f = files.next();
    const m = f.getName().match(pattern);
    if (m) {
      const d = new Date(m[1]);
      if (!latestDate || d > latestDate) {
        latestDate = d;
        latest = f;
      }
    }
  }

  if (!latest) {
    Logger.log('No to-be-expired files found in folder: ' + folderId);
    return;
  }

  Logger.log('Latest to-be-expired file: ' + latest.getName() + ' (' + latestDate + ')');

  // Convert using Drive API (supportsAllDrives)
  const fileId = latest.getId();
  const copyRequest = { title: 'Temp ToBeExpired - ' + latest.getName(), mimeType: 'application/vnd.google-apps.spreadsheet' };
  let converted = null;
  try {
    converted = Drive.Files.copy(copyRequest, fileId, {supportsAllDrives: true});
    Utilities.sleep(3000);
  } catch (e) {
    throw new Error('Drive.Files.copy failed for to-be-expired file: ' + e.message);
  }

  const convertedFile = DriveApp.getFileById(converted.id);
  const spreadsheet = SpreadsheetApp.open(convertedFile);
  const sheet = spreadsheet.getSheets()[0];
  const data = sheet.getDataRange().getValues();
  if (!data || data.length < 2) {
    Logger.log('No data found in to-be-expired file: ' + latest.getName());
    DriveApp.getFileById(converted.id).setTrashed(true);
    return;
  }

  const headers = data[0].map(h => String(h).trim());
  const rows = data.slice(1);

  // Find index of Expire_type header (case-insensitive)
  const expireIdx = headers.findIndex(h => /expire[_ ]?type/i.test(h));
  if (expireIdx === -1) {
    Logger.log('Expire_type header not found in to-be-expired file. Headers: ' + headers.join(','));
    DriveApp.getFileById(converted.id).setTrashed(true);
    return;
  }

  // Filter rows that are To-be-Expired only
  const toBeRows = rows.filter(r => {
    const v = r[expireIdx];
    return String(v).trim() === 'To-be-Expired';
  });

  if (toBeRows.length === 0) {
    Logger.log('No To-be-Expired rows found in latest file.');
    DriveApp.getFileById(converted.id).setTrashed(true);
    return;
  }

  // Map rows into JSON objects using headers
  const jsonRows = toBeRows.map(r => {
    const obj = {};
    headers.forEach((h, i) => {
      const key = String(h).replace(/\s+/g, '_');
      let val = r[i];
      // Normalize dates to YYYY-MM-DD for BigQuery DATE fields
      if (val instanceof Date) {
        val = val.toISOString().split('T')[0];
      }
      obj[key] = val === '' ? null : val;
    });
    return {json: obj};
  });

  // Delete previous To-be-Expired rows from BigQuery table
  const projectId = 'pccw-internal-virt-agent-uat';
  const datasetId = 'CostItemExpiration';
  const tableId = 'expired_cost_items';

  // Ensure the table has an Expire_type field (case-insensitive). If not, add it.
  try {
    const table = BigQuery.Tables.get(projectId, datasetId, tableId);
    const fields = (table.schema && table.schema.fields) || [];
    const hasExpire = fields.some(f => String(f.name).toLowerCase() === 'expire_type' || String(f.name).toLowerCase() === 'expiretype');
    if (!hasExpire) {
      const alterSql = `ALTER TABLE \`${projectId}.${datasetId}.${tableId}\` ADD COLUMN Expire_type STRING`;
      Logger.log('Expire_type column not found; running: ' + alterSql);
      const alterJob = BigQuery.Jobs.insert({
        configuration: { query: { query: alterSql, useLegacySql: false } }
      }, projectId);
      const alterJobId = alterJob.jobReference.jobId;
      // wait for alter to finish
      for (let j = 0; j < 20; j++) {
        const s = BigQuery.Jobs.get(projectId, alterJobId).status;
        if (s && s.state === 'DONE') {
          if (s.errorResult) throw new Error('BigQuery alter job failed: ' + JSON.stringify(s.errorResult));
          Logger.log('Alter table completed.');
          break;
        }
        Utilities.sleep(1000 * (j + 1));
      }
    }
  } catch (e) {
    Logger.log('Error checking/altering table schema: ' + e.message);
    throw e;
  }

  const deleteSql = `DELETE FROM \`${projectId}.${datasetId}.${tableId}\` WHERE Expire_type = 'To-be-Expired'`;
  Logger.log('Running delete query: ' + deleteSql);
  const job = BigQuery.Jobs.insert({
    configuration: { query: { query: deleteSql, useLegacySql: false } }
  }, projectId);
  const jobId = job.jobReference.jobId;
  // Wait for delete job to complete (simple polling)
  for (let i = 0; i < 20; i++) {
    const status = BigQuery.Jobs.get(projectId, jobId).status;
    if (status && status.state === 'DONE') {
      if (status.errorResult) {
        throw new Error('BigQuery delete job failed: ' + JSON.stringify(status.errorResult));
      }
      Logger.log('Delete job completed.');
      break;
    }
    Utilities.sleep(1000 * (i + 1));
  }

  // Insert the fresh To-be-Expired rows
  try {
    BigQuery.Tabledata.insertAll({ rows: jsonRows }, projectId, datasetId, tableId);
    Logger.log('Inserted ' + jsonRows.length + ' To-be-Expired rows into BigQuery.');
  } catch (e) {
    throw new Error('Failed to insert To-be-Expired rows: ' + e.message);
  }

  // Clean up
  DriveApp.getFileById(converted.id).setTrashed(true);
}

/**
 * Sets up a time-based trigger to run processNewFiles every hour.
 * Run this function once manually to create the trigger.
 */
function setupTrigger() {
  // Delete any existing triggers for this function
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'processNewFiles') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  // Create a new trigger to run every hour
  ScriptApp.newTrigger('processNewFiles')
    .timeBased()
    .everyHours(1)
    .create();
}

/**
 * Resets the last processed timestamp for testing (allows re-processing of existing files).
 */
function resetLastProcessed() {
  PropertiesService.getScriptProperties().deleteProperty('lastProcessed');
  Logger.log('Last processed timestamp reset.');
}

/**
 * Set last processed timestamp to a specific date/time.
 * This allows reprocessing files from a certain point in time.
 * @param {string} dateString - Date string in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'
 * Example: setLastProcessedToDate('2025-12-15') or setLastProcessedToDate('2025-12-15 00:00:00')
 */
function setLastProcessedToDate(dateString) {
  dateString = '2025-12-15'
  const targetDate = new Date(dateString);
  if (isNaN(targetDate.getTime())) {
    Logger.log('ERROR: Invalid date string: ' + dateString);
    Logger.log('Use format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS');
    return;
  }
  const timestamp = targetDate.getTime();
  PropertiesService.getScriptProperties().setProperty('lastProcessed', timestamp.toString());
  Logger.log('Last processed timestamp set to: ' + targetDate.toISOString() + ' (' + timestamp + ')');
  Logger.log('Files newer than this date will be processed on next run.');
}

/**
 * View current last processed timestamp
 */
function viewLastProcessed() {
  const lastProcessed = parseInt(PropertiesService.getScriptProperties().getProperty('lastProcessed')) || 0;
  if (lastProcessed === 0) {
    Logger.log('Last processed timestamp: NEVER (not set)');
  } else {
    Logger.log('Last processed timestamp: ' + new Date(lastProcessed).toISOString() + ' (' + lastProcessed + ')');
  }
}
