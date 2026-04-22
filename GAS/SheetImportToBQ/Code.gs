// Sheet1 → BigQuery import script
// Configure the constants below before first run.
const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const DATASET_ID = 'GSO';
const TABLE_ID = 'Staff';
// Primary key column in the sheet / target table (sanitized name)
const KEY_COLUMN = 'staff_id_number';
// When true, MERGE will set ingestion_time = CURRENT_TIMESTAMP() on insert/update
const USE_INGESTION_TIMESTAMP = true;

// Main entry: run manually or from a trigger
function importSheetToBigQuery() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('All GS&O Staffs');
  if (!sheet) {
    console.error('Sheet not found');
    return;
  }

  const values = sheet.getDataRange().getValues();
  if (!values || values.length < 2) {
    console.log('No data rows found (need header + at least one data row).');
    return;
  }

  const headersRaw = values[0].map(String);
  const headers = headersRaw.map(sanitizeHeader);

  // Ensure target table exists (fields as STRING)
  ensureTableExists(headers);

  // Build row objects from sheet data
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const rowVals = values[r];
    // Skip completely empty rows
    if (rowVals.every(c => c === '' || c === null || typeof c === 'undefined')) continue;
    const obj = {};
    for (let c = 0; c < headers.length; c++) {
      const v = rowVals[c];
      obj[headers[c]] = v === null || typeof v === 'undefined' ? null : String(v);
    }
  // add a load uuid to support dedup/trace when using temp table
  obj._load_uuid = Utilities.getUuid();
  // insertId helps BigQuery deduplicate within a single insertAll request
  rows.push({ insertId: Utilities.getUuid(), json: obj });
  }

  if (rows.length === 0) {
    console.log('No non-empty data rows to insert.');
    return;
  }

  // Use a temp table + MERGE into target to safely upsert
  const tempTableSuffix = Utilities.getUuid().replace(/-/g, '_');
  const tempTableId = TABLE_ID + '_tmp_' + tempTableSuffix;

  // Create temp table schema (add _load_uuid column)
  const tempHeaders = headers.concat(['_load_uuid']);
  createTable(PROJECT_ID, DATASET_ID, tempTableId, tempHeaders);

  // Wait for temp table to exist before inserting (may take a few seconds)
  const created = waitForTable(PROJECT_ID, DATASET_ID, tempTableId, 30000);
  if (!created) {
    console.error('Temp table not available after wait; aborting.');
    return;
  }

  // Batch insert into temp table
  // Deduplicate rows by KEY_COLUMN (keep last occurrence) to avoid MERGE "multiple source rows" error
  let rowsToInsert = rows;
  if (KEY_COLUMN) {
    const seen = {};
    const orderless = [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const keyVal = row.json[KEY_COLUMN];
      if (keyVal === null || typeof keyVal === 'undefined' || String(keyVal).trim() === '') {
        // preserve rows with empty/null key (they won't match target)
        orderless.push(row);
      } else {
        // keep last occurrence by overwriting
        seen[String(keyVal)] = row;
      }
    }
    rowsToInsert = orderless.concat(Object.keys(seen).map(k => seen[k]));
    if (rowsToInsert.length !== rows.length) {
      console.log('Deduplicated rows before insert: original=' + rows.length + ' deduped=' + rowsToInsert.length);
    }
  }

  const BATCH_SIZE = 500;
  for (let i = 0; i < rows.length; i += BATCH_SIZE) {
    const batch = rowsToInsert.slice(i, i + BATCH_SIZE);
    const insertBody = { rows: batch };
    try {
      const resp = BigQuery.Tabledata.insertAll(insertBody, PROJECT_ID, DATASET_ID, tempTableId);
      if (resp.insertErrors) {
        console.error('Insert errors for temp table batch starting at', i, resp.insertErrors);
      } else {
        console.log('Inserted batch into temp table', (i / BATCH_SIZE) + 1, ':', batch.length, 'rows');
      }
    } catch (err) {
      console.error('BigQuery insertAll failed for temp table batch starting at', i, err);
    }
  }

  // Build and run MERGE SQL to upsert from temp into target using KEY_COLUMN
  try {
    const mergeSql = buildMergeSql(PROJECT_ID, DATASET_ID, TABLE_ID, tempTableId, headers, KEY_COLUMN);
    const jobId = runQueryJob(mergeSql);
    waitForJob(PROJECT_ID, jobId, 600000); // wait up to 10 minutes
    console.log('Merge job completed:', jobId);
  } catch (err) {
    console.error('Merge job failed:', err);
  }

  // Try to delete temp table (best-effort)
  try {
    // Apps Script BigQuery advanced service may expose the delete operation
    // under different names depending on version; try known variants first.
    if (BigQuery && BigQuery.Tables && typeof BigQuery.Tables.remove === 'function') {
      BigQuery.Tables.remove(PROJECT_ID, DATASET_ID, tempTableId);
      console.log('Temp table deleted (remove):', tempTableId);
    } else if (BigQuery && BigQuery.Tables && typeof BigQuery.Tables.delete === 'function') {
      BigQuery.Tables.delete(PROJECT_ID, DATASET_ID, tempTableId);
      console.log('Temp table deleted (delete):', tempTableId);
    } else {
      // Fallback: run a DROP TABLE query job
      const dropSql = `DROP TABLE \`${PROJECT_ID}.${DATASET_ID}.${tempTableId}\``;
      try {
        const dropJobId = runQueryJob(dropSql);
        waitForJob(PROJECT_ID, dropJobId, 120000);
        console.log('Temp table dropped via query job:', tempTableId);
      } catch (qe) {
        throw qe;
      }
    }
  } catch (e) {
    console.warn('Could not delete temp table (ignored):', e.message || e);
  }

  console.log('Import complete. ' + rows.length + ' rows processed.');
}

// Create table if not exists. Fields are STRING type and named by sanitized headers.
function ensureTableExists(headers) {
  let tableExists = false;
  let existingFields = [];
  try {
    const table = BigQuery.Tables.get(PROJECT_ID, DATASET_ID, TABLE_ID);
    tableExists = true;
    existingFields = table.schema.fields.map(f => f.name);
    console.log('Table ' + TABLE_ID + ' exists in ' + DATASET_ID + ' with ' + existingFields.length + ' fields.');
  } catch (e) {
    if (!isNotFoundError(e)) throw e;
  }

  if (!tableExists) {
    createTable(PROJECT_ID, DATASET_ID, TABLE_ID, headers);
    return;
  }

  // Determine which columns to add and which to drop to replicate the sheet
  // Preserve KEY_COLUMN and optional ingestion_time even if not present in the sheet
  const preserve = new Set([KEY_COLUMN]);
  if (typeof USE_INGESTION_TIMESTAMP !== 'undefined' && USE_INGESTION_TIMESTAMP) {
    preserve.add('ingestion_time');
  }

  const missingFields = headers.filter(h => !existingFields.includes(h));
  const extraneousFields = existingFields.filter(f => !headers.includes(f) && !preserve.has(f));

  // Add missing columns
  if (missingFields.length > 0) {
    console.log('Adding missing columns to table: ' + missingFields.join(', '));
    const addSql = `ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` ` +
      missingFields.map(col => `ADD COLUMN ${col} STRING`).join(', ');
    try {
      const jobId = runQueryJob(addSql);
      waitForJob(PROJECT_ID, jobId, 120000); // wait up to 2 minutes
      console.log('Added columns to table: ' + missingFields.join(', '));
    } catch (err) {
      console.error('Failed to add columns: ', err);
      throw err;
    }
  }

  // Drop columns that are no longer present in the sheet (excluding preserved ones)
  if (extraneousFields.length > 0) {
    console.log('Dropping columns no longer in sheet: ' + extraneousFields.join(', '));
    const dropSql = `ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` ` +
      extraneousFields.map(col => `DROP COLUMN ${col}`).join(', ');
    try {
      const jobId = runQueryJob(dropSql);
      waitForJob(PROJECT_ID, jobId, 120000); // wait up to 2 minutes
      console.log('Dropped columns from table: ' + extraneousFields.join(', '));
    } catch (err) {
      console.error('Failed to drop columns: ', err);
      throw err;
    }
  }

  if (missingFields.length === 0 && extraneousFields.length === 0) {
    console.log('Table schema already matches sheet headers (with preserved columns).');
  }
}

// Helper to create a table with all STRING columns (fields array of names)
function createTable(projectId, datasetId, tableId, fields) {
  const schemaFields = fields.map(h => ({ name: h, type: 'STRING' }));
  const tableResource = {
    tableReference: {
      projectId: projectId,
      datasetId: datasetId,
      tableId: tableId
    },
    schema: { fields: schemaFields }
  };

  try {
    BigQuery.Tables.insert(tableResource, projectId, datasetId);
    console.log('Created table ' + tableId + ' with ' + fields.length + ' string fields.');
  } catch (err) {
    console.error('Failed to create table ' + tableId + ':', err);
    throw err;
  }
}

// Make header names valid BigQuery field names
function sanitizeHeader(orig) {
  let s = String(orig || '').trim();
  if (s.length === 0) s = 'field';
  s = s.replace(/[^\w]/g, '_');
  s = s.replace(/^(\d+)/, 'f_$1');
  s = s.replace(/__+/g, '_');
  s = s.toLowerCase();
  if (!/^[A-Za-z_]/.test(s)) s = 'f_' + s;
  return s.substring(0, 128);
}

function isNotFoundError(e) {
  try {
    const msg = (e && e.message) || String(e);
    return msg.indexOf('Not Found') !== -1 || msg.indexOf('404') !== -1;
  } catch (x) {
    return false;
  }
}

// Wait for a table to appear. Returns true if found within timeoutMs
function waitForTable(projectId, datasetId, tableId, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      BigQuery.Tables.get(projectId, datasetId, tableId);
      return true;
    } catch (e) {
      // keep waiting if Not Found
      if (!isNotFoundError(e)) {
        throw e;
      }
      Utilities.sleep(2000);
    }
  }
  return false;
}

// Run a query job and return jobId
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

// Wait for a job to finish. Throws on error or timeout.
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

// Build MERGE SQL for the provided columns. Uses KEY_COLUMN as the join key.
function buildMergeSql(projectId, datasetId, targetTable, tempTable, columns, keyColumn) {
  // exclude the load uuid column from merge into target
  const targetCols = columns.slice();
  const sourceCols = columns.slice();
  // ensure key is present
  if (targetCols.indexOf(keyColumn) === -1) {
    throw new Error('Key column ' + keyColumn + ' not found in sheet headers');
  }

  const quoted = name => '`' + projectId + '.' + datasetId + '.' + name + '`';
  const targetFqn = quoted(targetTable);
  const tempFqn = quoted(tempTable);

  // Use a deduping subquery for the source so MERGE sees at most one row per key
  // QUALIFY requires BigQuery Standard SQL
  const dedupSource = `(
    SELECT * FROM ${tempFqn}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ${keyColumn} ORDER BY _load_uuid DESC) = 1
  )`;

  // Build update set = col = S.col for non-key columns
  const nonKey = targetCols.filter(c => c !== keyColumn);
  let updateSet = nonKey.map(c => 'T.' + c + ' = S.' + c).join(',\n    ');

  // Optionally set ingestion_time on update/insert
  if (typeof USE_INGESTION_TIMESTAMP !== 'undefined' && USE_INGESTION_TIMESTAMP) {
    // add ingestion_time to update set
    updateSet = updateSet + (updateSet.length ? ',\n    ' : '') + 'T.ingestion_time = CURRENT_TIMESTAMP()';
  }

  // Build insert column list/values; optionally include ingestion_time
  const insertColsArr = targetCols.slice();
  const insertValsArr = targetCols.map(c => 'S.' + c);
  if (typeof USE_INGESTION_TIMESTAMP !== 'undefined' && USE_INGESTION_TIMESTAMP) {
    insertColsArr.push('ingestion_time');
    insertValsArr.push('CURRENT_TIMESTAMP()');
  }

  const insertCols = insertColsArr.join(', ');
  const insertVals = insertValsArr.join(', ');

  const sql = `MERGE ${targetFqn} T
USING ${dedupSource} S
ON T.${keyColumn} = S.${keyColumn}
WHEN MATCHED THEN
  UPDATE SET
    ${updateSet}
WHEN NOT MATCHED THEN
  INSERT (${insertCols})
  VALUES (${insertVals})`;

  return sql;
}

// Create a weekly trigger (example: every Monday at 02:00). Call once manually.
function createWeeklyTrigger() {
  ScriptApp.newTrigger('importSheet1ToBigQuery')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(2)
    .create();
  console.log('Weekly trigger created: importSheet1ToBigQuery every Monday at 02:00');
}

// Remove existing triggers for this function
function deleteExistingTriggers() {
  const all = ScriptApp.getProjectTriggers();
  for (let t of all) {
    if (t.getHandlerFunction() === 'importSheet1ToBigQuery') {
      ScriptApp.deleteTrigger(t);
    }
  }
  console.log('Existing importSheet1ToBigQuery triggers removed.');
}
