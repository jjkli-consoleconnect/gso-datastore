function getConsolidationExcludeSheets_() {
  return [
    'BigQuery-consolidated',
    // Alias used in some spreadsheets / older docs.
    'BQ-consolidated',
    'ConsolidationSummary',
    'ConsolidationErrors',
    'HeaderDump',
    'HeaderCheck',
    'SourceSpreadsheet',
    // Never consolidate operational/helper tabs
    (CONFIG && CONFIG.SHEETS && CONFIG.SHEETS.EMAIL_DETAILS) ? CONFIG.SHEETS.EMAIL_DETAILS : '[Email Details]',
    (CONFIG && CONFIG.SHEETS && CONFIG.SHEETS.REVIEW_QUEUE) ? CONFIG.SHEETS.REVIEW_QUEUE : '[Review Queue]',
    (CONFIG && CONFIG.AUDIT && CONFIG.AUDIT.SHADOW_SHEET_NAME) ? CONFIG.AUDIT.SHADOW_SHEET_NAME : '_AuditShadow'
  ];
}

function consolidateAllSimple() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const targetName = 'BigQuery-consolidated';
  let target = ss.getSheetByName(targetName);
  if (!target) target = ss.insertSheet(targetName);

  const targetHeaderIndexByKey = buildHeaderIndexByKey_([
    'System',
    'FailedDate',
    'FailedTime',
    'ResumedDate',
    'ResumedTime',
    'RepairedDate',
    'RepairedTime',
    'Segment',
    'Reason',
    'Event Type',
    'RecoveryProgress',
    'Service_Impact',
    'Total_No__of_ccts',
    'No__of_NR',
    'Remedy_Incident_No',
    'FailedTimeStamp',
    'ResumedTimeStamp',
    'RepairedTimeStamp',
    'DownTime_mins',
    'OutageID',
    'RowAddedAt',
    'LastUpdatedAt'
  ]);

  function isExcludedReviewStatus_(v) {
    const s = String(v == null ? '' : v).trim().toLowerCase();
    return s === 'pending' || s === 'rejected';
  }

  // Ensure the consolidated sheet has enough columns for the canonical schema.
  try {
    const neededCols = 22;
    const existingCols = target.getMaxColumns();
    if (existingCols < neededCols) {
      target.insertColumnsAfter(existingCols, neededCols - existingCols);
    }
  } catch (e) { /* ignore */ }

  const exclude = getConsolidationExcludeSheets_();
  const sheets = ss.getSheets();

  // Canonical consolidated schema (A..T).
  // OutageID should be canonicalized here so downstream sync does not preserve
  // legacy SEGMENT/T000000/N2 variants as separate outages.
  const HEADER = targetHeaderIndexByKey.headers;

  // Columns P..S (16..19) contain formulas in the consolidated sheet.
  // Do NOT clear or overwrite them.
  const LEFT_COLS = 15; // A..O
  const OUTAGEID_COL = 20; // T
  const META_COL_START = 21; // U
  const META_COL_COUNT = 2;
  const rowsLeft = [];
  const rowsOutageId = [];
  const rowsMeta = [];

  for (let i = 0; i < sheets.length; i++) {
    const sh = sheets[i];
    const name = sh.getName();
    if (exclude.indexOf(name) !== -1) continue;
    const lastCol = sh.getLastColumn();
    const lastRow = sh.getLastRow();
    if (lastCol === 0 || lastRow <= 1) continue;
    const srcHeader = sh.getRange(1, 1, 1, lastCol).getValues()[0];
    const data = sh.getRange(2, 1, lastRow - 1, lastCol).getValues();

    const srcIndexByKey = {};
    for (let c = 0; c < srcHeader.length; c++) {
      const k = normalizeHeaderKey_(srcHeader[c]);
      if (!k) continue;
      // Keep the RIGHT-MOST match to prefer the trailing audit block for duplicates.
      srcIndexByKey[k] = c;
    }

    for (let r = 0; r < data.length; r++) {
      const srcRow = data[r];
      const nonEmpty = srcRow.some(c => c !== null && c !== '');
      if (!nonEmpty) continue;

      // Skip rows that are explicitly not ready for consolidation.
      // BigQuery-consolidated should ignore ReviewStatus Pending and Rejected.
      const reviewStatusIdx = srcIndexByKey['reviewstatus'];
      if (reviewStatusIdx != null && reviewStatusIdx >= 0 && reviewStatusIdx < srcRow.length) {
        if (isExcludedReviewStatus_(srcRow[reviewStatusIdx])) continue;
      }

      const outLeft = new Array(LEFT_COLS).fill('');
      outLeft[0] = name;

      // Map/copy A..N by header name.
      for (let j = 1; j < LEFT_COLS; j++) {
        const field = HEADER[j];
        const key = normalizeHeaderKey_(field);
        const idx = srcIndexByKey[key];
        if (idx == null) continue;
        if (idx < 0 || idx >= srcRow.length) continue;
        outLeft[j] = srcRow[idx];
      }

      const outageIdVal = resolveConsolidatedOutageId_(name, srcRow, srcIndexByKey);
      const rowAddedAtVal = srcIndexByKey['rowaddedat'] != null ? srcRow[srcIndexByKey['rowaddedat']] : '';
      const lastUpdatedAtVal = srcIndexByKey['lastupdatedat'] != null ? srcRow[srcIndexByKey['lastupdatedat']] : '';

      rowsLeft.push(outLeft);
      rowsOutageId.push([outageIdVal]);
      rowsMeta.push([rowAddedAtVal || '', lastUpdatedAtVal || '']);
    }
  }

  const dataRowCount = rowsLeft.length;

  // Ensure the sheet has enough rows for the output.
  try {
    const neededRows = dataRowCount + 1; // + header
    const existingRows = target.getMaxRows();
    if (existingRows < neededRows) {
      target.insertRowsAfter(existingRows, neededRows - existingRows);
    }
  } catch (e) { /* ignore */ }

  // Clear A..O and T only; preserve formula columns P..S.
  try {
    const maxRows = target.getMaxRows();
    if (maxRows > 1) {
      target.getRange(2, 1, Math.max(1, maxRows - 1), LEFT_COLS).clearContent();
      target.getRange(2, OUTAGEID_COL, Math.max(1, maxRows - 1), 1).clearContent();
      target.getRange(2, META_COL_START, Math.max(1, maxRows - 1), META_COL_COUNT).clearContent();
    }
  } catch (e) { /* ignore */ }

  try {
    // Always enforce canonical consolidated header.
    target.getRange(1, 1, 1, HEADER.length).setValues([HEADER]);
  } catch (e) { /* ignore */ }

  if (dataRowCount > 0) {
    try { target.getRange(2, 1, dataRowCount, LEFT_COLS).setValues(rowsLeft); } catch (e) { /* ignore */ }
    try { target.getRange(2, OUTAGEID_COL, dataRowCount, 1).setValues(rowsOutageId); } catch (e) { /* ignore */ }
    try { target.getRange(2, META_COL_START, dataRowCount, META_COL_COUNT).setValues(rowsMeta); } catch (e) { /* ignore */ }
  }

  try {
    fillFormulasInConsolidated(2, 16, 19, dataRowCount, HEADER);
  } catch (e) { /* ignore */ }

  const log = ss.getSheetByName('ConsolidationSummary') || ss.insertSheet('ConsolidationSummary');
  log.appendRow([new Date(), 'consolidateAllSimple', 'sheets', sheets.length, 'rowsWritten', dataRowCount]);

  // After consolidation completes, flush buffered audit edits to BigQuery.
  // Workflow is centralized in SyncService.
  try {
    if (typeof syncAuditAfterConsolidation === 'function') {
      syncAuditAfterConsolidation({
        reason: 'consolidateAllSimple',
        rowsWritten: dataRowCount,
        sheetsScanned: sheets.length,
        targetSheetName: targetName
      });
    } else if (typeof flushAuditNow === 'function') {
      flushAuditNow();
    }
  } catch (e) {
    try { Logger.log('Audit flush after consolidation failed: ' + e); } catch (ignore) {}
  }
}

function normalizeHeaderKey_(v) {
  return String(v || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/_/g, '');
}

function resolveConsolidatedOutageId_(systemName, srcRow, srcIndexByKey) {
  function cell(headerKey) {
    const idx = srcIndexByKey[headerKey];
    if (idx == null || idx < 0 || idx >= srcRow.length) return '';
    return srcRow[idx];
  }

  const sourceOutageId = cell('outageid');
  const failedForId = cell('faileddate') || cell('failedtimestamp');

  if (typeof _buildOutageIdFromFields_ === 'function') {
    const canonicalOutageId = _buildOutageIdFromFields_(systemName, cell('segment'), failedForId);
    if (_isUsableCanonicalOutageId_(canonicalOutageId)) {
      return canonicalOutageId;
    }
  }

  return sourceOutageId || '';
}

function _isUsableCanonicalOutageId_(outageId) {
  const normalized = String(outageId || '').trim().toUpperCase();
  return !!normalized &&
    normalized.indexOf('00000000-') !== 0 &&
    normalized.indexOf('-UNKWN-') === -1 &&
    normalized.indexOf('-SUNKNOWN') === -1;
}

function buildHeaderIndexByKey_(headers) {
  const normalizedHeaders = (headers || []).slice();
  const indexByKey = {};
  for (let i = 0; i < normalizedHeaders.length; i++) {
    const key = normalizeHeaderKey_(normalizedHeaders[i]);
    if (!key) continue;
    indexByKey[key] = i + 1;
  }
  return {
    headers: normalizedHeaders,
    indexByKey: indexByKey
  };
}

function buildConsolidatedRowFormulaMap_(rowNum, headerRow) {
  const normalized = buildHeaderIndexByKey_(headerRow || []).indexByKey;

  function cell(headerName) {
    const colNum = normalized[normalizeHeaderKey_(headerName)];
    if (!colNum) throw new Error('Missing consolidated header: ' + headerName);
    return '$' + colToA1Letter_(colNum) + rowNum;
  }

  function buildTimestampFormula(dateHeader, timeHeader) {
    const dateCell = cell(dateHeader);
    const timeCell = cell(timeHeader);
    return '=IF(OR(' + dateCell + '="",' + timeCell + '=""),"",'
      + 'IFERROR(DATEVALUE(' + dateCell + '),' + dateCell + ')+'
      + 'IFERROR(TIMEVALUE(' + timeCell + '),' + timeCell + '))';
  }

  const failedTsFormula = buildTimestampFormula('FailedDate', 'FailedTime');
  const resumedTsFormula = buildTimestampFormula('ResumedDate', 'ResumedTime');
  const repairedTsFormula = buildTimestampFormula('RepairedDate', 'RepairedTime');
  const failedTsCell = cell('FailedTimeStamp');
  const resumedTsCell = cell('ResumedTimeStamp');

  const downTimeFormula = '=IF(OR(' + failedTsCell + '="",' + resumedTsCell + '=""),"",'
    + 'ROUND((' + resumedTsCell + '-' + failedTsCell + ')*24*60,0))';

  return {
    FailedTimeStamp: failedTsFormula,
    ResumedTimeStamp: resumedTsFormula,
    RepairedTimeStamp: repairedTsFormula,
    DownTime_mins: downTimeFormula
  };
}

function fillFormulasInConsolidated(srcRow, startCol, endCol, dataRowCount, headerRow) {
  srcRow = srcRow || 2; startCol = startCol || 16; endCol = endCol || 19;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const target = ss.getSheetByName('BigQuery-consolidated');
  if (!target) return;
  const numCols = endCol - startCol + 1;
  dataRowCount = dataRowCount || 0;

  const headers = headerRow && headerRow.length
    ? headerRow.slice()
    : target.getRange(1, 1, 1, Math.max(endCol, target.getLastColumn())).getValues()[0];
  const formulaFieldOrder = [
    'FailedTimeStamp',
    'ResumedTimeStamp',
    'RepairedTimeStamp',
    'DownTime_mins'
  ];

  const templateFormulas = buildConsolidatedRowFormulaMap_(srcRow, headers);
  const templateRow = formulaFieldOrder.map(fieldName => templateFormulas[fieldName]);

  try {
    target.getRange(srcRow, startCol, 1, numCols).setFormulas([templateRow]);
  } catch (e) { /* ignore */ }

  try {
    const formatRowCount = Math.max(1, target.getMaxRows() - srcRow + 1);
    target.getRange(srcRow, startCol, formatRowCount, 3).setNumberFormat('yyyy-mm-dd hh:mm:ss');
    target.getRange(srcRow, endCol, formatRowCount, 1).setNumberFormat('0');
  } catch (e) { /* ignore */ }

  const rowsNeedingFormulas = Math.max(0, dataRowCount - 1);
  try {
    if (rowsNeedingFormulas > 0) {
      const formulas = [];
      for (let rowOffset = 1; rowOffset <= rowsNeedingFormulas; rowOffset++) {
        const rowNum = srcRow + rowOffset;
        const rowFormulas = buildConsolidatedRowFormulaMap_(rowNum, headers);
        formulas.push(formulaFieldOrder.map(fieldName => rowFormulas[fieldName]));
      }
      target.getRange(srcRow + 1, startCol, rowsNeedingFormulas, numCols).setFormulas(formulas);
    }
  } catch (e) { /* ignore */ }

  const clearStartRow = srcRow + Math.max(dataRowCount, 1);
  const maxRows = target.getMaxRows();
  if (clearStartRow <= maxRows) {
    const rowsToClear = maxRows - clearStartRow + 1;
    if (rowsToClear > 0) {
      try {
        target.getRange(clearStartRow, startCol, rowsToClear, numCols).clearContent();
      } catch (e) { /* ignore */ }
    }
  }
}

// Menu creation is handled by Main.gs (single onOpen source of truth).

function installInvalidDateTimeHighlighting() {
  // Runs in batches to avoid script execution timeouts.
  // Uses DocumentProperties to track progress.
  try {
    const props = PropertiesService.getDocumentProperties();
    props.setProperty('INVALID_DT_HL_NEXT_INDEX', '0');
  } catch (e) { /* ignore */ }
  processInvalidDateTimeHighlightingBatch_();
}

function processInvalidDateTimeHighlightingBatch_() {
  const startMs = Date.now();
  const maxMs = 25000; // keep safely under the per-execution limit
  const maxSheetsPerRun = 8;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const exclude = getConsolidationExcludeSheets_();
  const sheets = ss.getSheets();

  const props = PropertiesService.getDocumentProperties();
  let idx = 0;
  try {
    idx = Number(props.getProperty('INVALID_DT_HL_NEXT_INDEX') || '0') || 0;
  } catch (e) { idx = 0; }

  let processed = 0;
  for (; idx < sheets.length; idx++) {
    if (Date.now() - startMs > maxMs) break;
    if (processed >= maxSheetsPerRun) break;
    try {
      const sh = sheets[idx];
      const name = sh && sh.getName ? sh.getName() : '';
      if (exclude && exclude.indexOf(name) !== -1) continue;
      ensureInvalidDateTimeHighlightingOnSheet_(sh);
      processed++;
    } catch (e) { /* ignore */ }
  }

  if (idx >= sheets.length) {
    try { props.deleteProperty('INVALID_DT_HL_NEXT_INDEX'); } catch (e) { /* ignore */ }
    cleanupInvalidDateTimeHighlightingTriggers_();
    return;
  }

  try { props.setProperty('INVALID_DT_HL_NEXT_INDEX', String(idx)); } catch (e) { /* ignore */ }
  scheduleInvalidDateTimeHighlightingContinuation_();
}

function scheduleInvalidDateTimeHighlightingContinuation_() {
  try {
    const triggers = ScriptApp.getProjectTriggers() || [];
    for (let i = 0; i < triggers.length; i++) {
      if (triggers[i] && triggers[i].getHandlerFunction && triggers[i].getHandlerFunction() === 'processInvalidDateTimeHighlightingBatch_') {
        return; // already scheduled
      }
    }
  } catch (e) { /* ignore */ }

  try {
    ScriptApp.newTrigger('processInvalidDateTimeHighlightingBatch_')
      .timeBased()
      .after(2000)
      .create();
  } catch (e) { /* ignore */ }
}

function cleanupInvalidDateTimeHighlightingTriggers_() {
  try {
    const triggers = ScriptApp.getProjectTriggers() || [];
    for (let i = 0; i < triggers.length; i++) {
      const t = triggers[i];
      if (t && t.getHandlerFunction && t.getHandlerFunction() === 'processInvalidDateTimeHighlightingBatch_') {
        try { ScriptApp.deleteTrigger(t); } catch (ignore) {}
      }
    }
  } catch (e) { /* ignore */ }
}

function ensureInvalidDateTimeHighlightingAllSheets_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const exclude = getConsolidationExcludeSheets_();
  const sheets = ss.getSheets();
  for (let i = 0; i < sheets.length; i++) {
    try {
      const sh = sheets[i];
      const name = sh && sh.getName ? sh.getName() : '';
      if (exclude && exclude.indexOf(name) !== -1) continue;
      ensureInvalidDateTimeHighlightingOnSheet_(sheets[i]);
    } catch (e) { /* ignore */ }
  }
}

function ensureInvalidDateTimeHighlightingActiveSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const exclude = getConsolidationExcludeSheets_();
  const sh = ss.getActiveSheet();
  if (!sh) return;
  try {
    const name = sh.getName();
    if (exclude && exclude.indexOf(name) !== -1) return;
  } catch (e) { /* ignore */ }
  ensureInvalidDateTimeHighlightingOnSheet_(sh);
}

function ensureInvalidDateTimeHighlightingOnSheet_(sheet) {
  if (!sheet) return;
  const lastCol = sheet.getLastColumn();
  const lastRow = sheet.getLastRow();
  if (lastCol <= 0 || lastRow <= 1) return;

  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0] || [];
  const headerIndexByKey = {};
  for (let c = 0; c < headers.length; c++) {
    const k = normalizeHeaderKeyForRules_(headers[c]);
    if (!k) continue;
    headerIndexByKey[k] = c + 1; // 1-based
  }

  // Prefer *TimeStamp columns when present; otherwise fall back to Date+Time columns.
  // Many source tabs only have FailedDate/FailedTime/etc.
  const failedTsCol = headerIndexByKey['failedtimestamp'];
  const resumedTsCol = headerIndexByKey['resumedtimestamp'];
  const repairedTsCol = headerIndexByKey['repairedtimestamp'];

  const failedDateCol = headerIndexByKey['faileddate'];
  const failedTimeCol = headerIndexByKey['failedtime'];
  const resumedDateCol = headerIndexByKey['resumeddate'];
  const resumedTimeCol = headerIndexByKey['resumedtime'];
  const repairedDateCol = headerIndexByKey['repaireddate'];
  const repairedTimeCol = headerIndexByKey['repairedtime'];

  const hasTs = !!(failedTsCol && resumedTsCol && repairedTsCol);
  const hasDateTime = !!(
    failedDateCol && failedTimeCol &&
    resumedDateCol && resumedTimeCol &&
    repairedDateCol && repairedTimeCol
  );

  if (!hasTs && !hasDateTime) return;

  // Highlight the entire row block, not just the timestamp cells.
  const range = sheet.getRange(2, 1, Math.max(1, lastRow - 1), lastCol);

  let formula = '';
  if (hasTs && !hasDateTime) {
    const failedLetter = colToA1Letter_(failedTsCol);
    const resumedLetter = colToA1Letter_(resumedTsCol);
    const repairedLetter = colToA1Letter_(repairedTsCol);

    formula = '=OR('
      + 'AND($' + failedLetter + '2<>"",$' + resumedLetter + '2<>"",$' + resumedLetter + '2<$' + failedLetter + '2),'
      + 'AND($' + failedLetter + '2<>"",$' + repairedLetter + '2<>"",$' + repairedLetter + '2<$' + failedLetter + '2)'
      + ')';
  } else if (!hasTs && hasDateTime) {
    const fdl = colToA1Letter_(failedDateCol);
    const ftl = colToA1Letter_(failedTimeCol);
    const rdl = colToA1Letter_(resumedDateCol);
    const rtl = colToA1Letter_(resumedTimeCol);
    const pdl = colToA1Letter_(repairedDateCol);
    const ptl = colToA1Letter_(repairedTimeCol);

    // Build a datetime from separate Date + Time.
    // IFERROR handles both native date/time values (numbers) and textual values.
    const failedDT = '(IFERROR(DATEVALUE($' + fdl + '2),$' + fdl + '2)+IFERROR(TIMEVALUE($' + ftl + '2),$' + ftl + '2))';
    const resumedDT = '(IFERROR(DATEVALUE($' + rdl + '2),$' + rdl + '2)+IFERROR(TIMEVALUE($' + rtl + '2),$' + rtl + '2))';
    const repairedDT = '(IFERROR(DATEVALUE($' + pdl + '2),$' + pdl + '2)+IFERROR(TIMEVALUE($' + ptl + '2),$' + ptl + '2))';

    formula = '=OR('
      + 'AND($' + fdl + '2<>"",$' + ftl + '2<>"",$' + rdl + '2<>"",$' + rtl + '2<>"",' + resumedDT + '<' + failedDT + '),'
      + 'AND($' + fdl + '2<>"",$' + ftl + '2<>"",$' + pdl + '2<>"",$' + ptl + '2<>"",' + repairedDT + '<' + failedDT + ')'
      + ')';
  } else {
    // Both sets exist: check timestamps when present, otherwise check Date+Time.
    const failedLetter = colToA1Letter_(failedTsCol);
    const resumedLetter = colToA1Letter_(resumedTsCol);
    const repairedLetter = colToA1Letter_(repairedTsCol);

    const fdl = colToA1Letter_(failedDateCol);
    const ftl = colToA1Letter_(failedTimeCol);
    const rdl = colToA1Letter_(resumedDateCol);
    const rtl = colToA1Letter_(resumedTimeCol);
    const pdl = colToA1Letter_(repairedDateCol);
    const ptl = colToA1Letter_(repairedTimeCol);

    const failedDT = '(IFERROR(DATEVALUE($' + fdl + '2),$' + fdl + '2)+IFERROR(TIMEVALUE($' + ftl + '2),$' + ftl + '2))';
    const resumedDT = '(IFERROR(DATEVALUE($' + rdl + '2),$' + rdl + '2)+IFERROR(TIMEVALUE($' + rtl + '2),$' + rtl + '2))';
    const repairedDT = '(IFERROR(DATEVALUE($' + pdl + '2),$' + pdl + '2)+IFERROR(TIMEVALUE($' + ptl + '2),$' + ptl + '2))';

    formula = '=OR('
      + 'AND($' + failedLetter + '2<>"",$' + resumedLetter + '2<>"",$' + resumedLetter + '2<$' + failedLetter + '2),'
      + 'AND($' + failedLetter + '2<>"",$' + repairedLetter + '2<>"",$' + repairedLetter + '2<$' + failedLetter + '2),'
      + 'AND($' + fdl + '2<>"",$' + ftl + '2<>"",$' + rdl + '2<>"",$' + rtl + '2<>"",' + resumedDT + '<' + failedDT + '),'
      + 'AND($' + fdl + '2<>"",$' + ftl + '2<>"",$' + pdl + '2<>"",$' + ptl + '2<>"",' + repairedDT + '<' + failedDT + ')'
      + ')';
  }

  const existing = sheet.getConditionalFormatRules() || [];
  for (let i = 0; i < existing.length; i++) {
    if (isInvalidDateTimeRule_(existing[i], formula)) return;
  }
  const kept = [];
  for (let i = 0; i < existing.length; i++) {
    const rule = existing[i];
    if (!isInvalidDateTimeRule_(rule, formula)) kept.push(rule);
  }

  const invalidRule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied(formula)
    .setBackground('#ffcccc')
    .setRanges([range])
    .build();

  kept.push(invalidRule);
  sheet.setConditionalFormatRules(kept);
}

function isInvalidDateTimeRule_(rule, formula) {
  if (!rule) return false;
  try {
    const bc = rule.getBooleanCondition();
    if (!bc) return false;
    if (bc.getCriteriaType() !== SpreadsheetApp.BooleanCriteria.CUSTOM_FORMULA) return false;
    const vals = bc.getCriteriaValues() || [];
    const f = String(vals[0] || '');
    return formula && f === String(formula);
  } catch (e) {
    return false;
  }
}

function normalizeHeaderKeyForRules_(v) {
  return String(v || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/_/g, '');
}

function colToA1Letter_(col) {
  let n = Number(col || 0);
  if (!n || n < 1) return 'A';
  let s = '';
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}
