/**
 * One-time installer for ReviewStatus dropdown + highlight cleanup.
 *
 * Requirements:
 * - Existing records stay as-is (no backfill).
 * - New backend-written rows should already be written with ReviewStatus=Pending.
 * - Rows highlighted yellow while Pending; highlight removed on status change.
 * - Manual input is allowed (dropdown is non-enforcing; blanks/other values allowed).
 */

function installReviewStatusDropdowns() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Create/update the installable trigger (safe to run multiple times).
  _ensureInstallableTrigger_('handleReviewStatusEdit_');

  const sheets = _getEligibleSheetsForReviewStatus_(ss);
  const allowed = [
    CONFIG.REVIEW_STATUS.PENDING,
    CONFIG.REVIEW_STATUS.APPROVED,
    CONFIG.REVIEW_STATUS.MODIFIED,
    CONFIG.REVIEW_STATUS.REJECTED
  ];

  const rule = SpreadsheetApp
    .newDataValidation()
    .requireValueInList(allowed, true)
    // Do NOT enforce. This keeps manual edits allowed and allows blanks.
    .setAllowInvalid(true)
    .build();

  let updatedSheets = 0;
  let createdHeaderSheets = 0;
  let skippedSheets = 0;

  sheets.forEach(sheet => {
    const ensured = _ensureReviewAuditHeaders_(sheet);
    if (!ensured || !ensured.statusCol) {
      skippedSheets++;
      return;
    }

    const statusCol = ensured.statusCol;
    if (ensured.createdHeaders) createdHeaderSheets++;

    const maxRows = sheet.getMaxRows();
    if (maxRows < 2) return;

    // Apply validation to the whole column below header.
    const range = sheet.getRange(2, statusCol, maxRows - 1, 1);
    range.setDataValidation(rule);

    // Ensure validation is ONLY applied to ReviewStatus.
    // Some older installers (and/or manual copy/paste) left identical validations
    // on adjacent audit columns, causing Sheets UI to show a multi-column range
    // like O2:R1520. Clear validations on the other audit columns.
    try {
      const auditCols = ensured.auditCols || {};
      const otherCols = [auditCols.OutageID, auditCols.EmailID, auditCols.EmailDateTime].filter(c => !!c);
      otherCols.forEach(colIdx => {
        try {
          sheet.getRange(2, colIdx, maxRows - 1, 1).clearDataValidations();
        } catch (e) {
          // ignore
        }
      });
    } catch (e) {
      // ignore
    }

    // Cleanup: before Event Type was inserted, ReviewStatus lived in column O (15).
    // If a stale dropdown remains there, clear it so RemedyTicket is not dropdown-backed.
    try {
      const legacyStatusCol = 15;
      if (statusCol !== legacyStatusCol && maxRows >= 2 && legacyStatusCol <= sheet.getMaxColumns()) {
        sheet.getRange(2, legacyStatusCol, maxRows - 1, 1).clearDataValidations();
      }
    } catch (e) {
      // ignore
    }

    // Cleanup: older installer versions mistakenly fell back to column 3.
    // If ReviewStatus is NOT column C, clear *all* data validations in column C
    // (this fixes sheets where FailedTime lives in column C and was incorrectly dropdown'd).
    try {
      if (statusCol !== 3 && maxRows >= 2) {
        sheet.getRange(2, 3, maxRows - 1, 1).clearDataValidations();
      }
    } catch (e) {
      // ignore
    }

    updatedSheets++;
  });

  SpreadsheetApp.getUi().alert(
    'ReviewStatus install complete.\n\n' +
      'Updated dropdown validation on ' + updatedSheets + ' sheet(s).\n' +
      'Created missing headers on ' + createdHeaderSheets + ' sheet(s).\n' +
      'Skipped ' + skippedSheets + ' sheet(s) (could not create/find headers).\n' +
      'Installed onEdit trigger to clear yellow highlight when status changes.'
  );
}

function _ensureReviewAuditHeaders_(sheet) {
  if (!sheet) return null;

  // [Review Queue] has its own column layout (it is not a system tab with a trailing audit block).
  // Do NOT try to append/migrate audit columns here; just ensure its headers exist and locate ReviewStatus.
  try {
    if (CONFIG && CONFIG.SHEETS && sheet.getName() === CONFIG.SHEETS.REVIEW_QUEUE) {
      try {
        if (typeof ensureReviewQueueHeaders === 'function') {
          ensureReviewQueueHeaders();
        }
      } catch (e) {
        // ignore
      }

      const lastCol = sheet.getLastColumn();
      if (lastCol < 1) return null;
      const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];

      let statusCol = null;
      for (let i = 0; i < headers.length; i++) {
        const key = _normalizeHeaderKey_(headers[i]);
        if (key === 'reviewstatus' || key === 'reviewerstatus') {
          statusCol = i + 1;
          break;
        }
      }
      if (!statusCol) return null;

      return {
        statusCol,
        createdHeaders: false,
        auditCols: { ReviewStatus: statusCol },
      };
    }
  } catch (e) {
    // ignore
  }

  // Desired trailing audit columns (exact order, exact spelling).
  const desired = ['ReviewStatus', 'OutageID', 'EmailID', 'EmailDateTime', 'RowAddedAt', 'LastUpdatedAt'];

  function _trimTrailingEmptyHeaders_(hdrs) {
    const copy = (hdrs || []).slice();
    while (copy.length > 0 && String(copy[copy.length - 1] || '').trim() === '') {
      copy.pop();
    }
    return copy;
  }

  function _matchesHeaderKey_(actual, expected) {
    if (actual === expected) return true;
    if (expected === 'reviewstatus' && actual === 'reviewerstatus') return true;
    if (expected === 'emailid' && actual === 'emailids') return true;
    if (expected === 'emaildatetime' && actual === 'emailtimestamp') return true;
    return false;
  }

  function _isPreEventTypeOutageSchema_(hdrs) {
    const trimmed = _trimTrailingEmptyHeaders_(hdrs);
    const keys = trimmed.map(_normalizeHeaderKey_);
    const expected = [
      'system',
      'faileddate',
      'failedtime',
      'resumeddate',
      'resumedtime',
      'repaireddate',
      'repairedtime',
      'segment',
      'reason',
      'recoveryprogress',
      'serviceimpact',
      'noofcircuits',
      'nononrestored',
      'remedyticket',
      'reviewstatus',
      'outageid',
      'emailid',
      'emaildatetime',
      'rowaddedat',
      'lastupdatedat'
    ];

    if (keys.length !== expected.length) return false;
    if (keys.indexOf('eventtype') !== -1) return false;

    for (let i = 0; i < expected.length; i++) {
      if (!_matchesHeaderKey_(keys[i], expected[i])) {
        return false;
      }
    }
    return true;
  }

  function _migratePreEventTypeOutageSchema_(currentHeaders) {
    const newHeaders = [
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
      'Service Impact',
      'NoOfCircuits',
      'NoNonRestored',
      'RemedyTicket',
      'ReviewStatus',
      'OutageID',
      'EmailID',
      'EmailDateTime',
      'RowAddedAt',
      'LastUpdatedAt'
    ];

    const headerIndex = {};
    _trimTrailingEmptyHeaders_(currentHeaders).forEach((h, i) => {
      headerIndex[_normalizeHeaderKey_(h)] = i;
    });

    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    const numRows = Math.max(0, lastRow - 1);
    const data = numRows > 0
      ? sheet.getRange(2, 1, numRows, lastCol).getValues()
      : [];

    function cell(row, headerKeys) {
      for (let i = 0; i < headerKeys.length; i++) {
        const idx = headerIndex[headerKeys[i]];
        if (idx == null) continue;
        return idx < row.length ? row[idx] : '';
      }
      return '';
    }

    const migrated = data.map(row => [
      cell(row, ['system']),
      cell(row, ['faileddate']),
      cell(row, ['failedtime']),
      cell(row, ['resumeddate']),
      cell(row, ['resumedtime']),
      cell(row, ['repaireddate']),
      cell(row, ['repairedtime']),
      cell(row, ['segment']),
      cell(row, ['reason']),
      '',
      cell(row, ['recoveryprogress']),
      cell(row, ['serviceimpact']),
      cell(row, ['noofcircuits']),
      cell(row, ['nononrestored']),
      cell(row, ['remedyticket']),
      cell(row, ['reviewstatus', 'reviewerstatus']),
      cell(row, ['outageid']),
      cell(row, ['emailid', 'emailids']),
      cell(row, ['emaildatetime', 'emailtimestamp']),
      '',
      ''
    ]);

    const maxCols = sheet.getMaxColumns();
    if (maxCols < newHeaders.length) {
      sheet.insertColumnsAfter(maxCols, newHeaders.length - maxCols);
    }

    if (lastRow > 0 && lastCol > 0) {
      sheet.getRange(1, 1, lastRow, lastCol).clearContent();
    }

    sheet.getRange(1, 1, 1, newHeaders.length).setValues([newHeaders]).setFontWeight('bold');
    if (migrated.length > 0) {
      sheet.getRange(2, 1, migrated.length, newHeaders.length).setValues(migrated);
    }

    try {
      sheet.setFrozenRows(1);
    } catch (e) {
      // ignore
    }
  }

  // If the sheet is totally empty, we can safely create a minimal header row.
  let lastCol = sheet.getLastColumn();
  let lastRow = sheet.getLastRow();

  // Read existing headers if present.
  let headers = (lastRow >= 1 && lastCol >= 1)
    ? sheet.getRange(1, 1, 1, lastCol).getValues()[0]
    : [];

  if (_isPreEventTypeOutageSchema_(headers)) {
    _migratePreEventTypeOutageSchema_(headers);
    lastCol = sheet.getLastColumn();
    lastRow = sheet.getLastRow();
    headers = (lastRow >= 1 && lastCol >= 1)
      ? sheet.getRange(1, 1, 1, lastCol).getValues()[0]
      : [];
  }

  function _findCanonicalCols_(hdrs) {
    const cols = {
      ReviewStatus: null,
      OutageID: null,
      EmailID: null,
      EmailDateTime: null,
      RowAddedAt: null,
      LastUpdatedAt: null,
    };

    for (let i = 0; i < hdrs.length; i++) {
      const key = _normalizeHeaderKey_(hdrs[i]);
      if (!cols.ReviewStatus && (key === 'reviewstatus' || key === 'reviewerstatus')) cols.ReviewStatus = i + 1;
      if (!cols.OutageID && key === 'outageid') cols.OutageID = i + 1;
      // Accept legacy plural header spellings but canonicalize to EmailID.
      if (!cols.EmailID && (key === 'emailid' || key === 'emailids')) cols.EmailID = i + 1;
      if (!cols.EmailDateTime && (key === 'emaildatetime' || key === 'emailtimestamp')) cols.EmailDateTime = i + 1;
      if (!cols.RowAddedAt && key === 'rowaddedat') cols.RowAddedAt = i + 1;
      if (!cols.LastUpdatedAt && key === 'lastupdatedat') cols.LastUpdatedAt = i + 1;
    }
    return cols;
  }

  function _canonicalizeHeaderCell_(colIndex, canonicalName) {
    try {
      if (colIndex && colIndex >= 1) {
        sheet.getRange(1, colIndex, 1, 1).setValue(canonicalName);
      }
    } catch (e) {
      // ignore
    }
  }

  // Identify existing columns (accept legacy spellings).
  const cols0 = _findCanonicalCols_(headers);

  // If we already have the desired 4 columns, in the desired order, at the end,
  // keep them in place; just normalize header spelling and formatting.
  const allPresent = desired.every(h => cols0[h]);
  if (allPresent) {
    const last = sheet.getLastColumn();
    const orderedAtEnd = (
      cols0.ReviewStatus === last - 5 &&
      cols0.OutageID === last - 4 &&
      cols0.EmailID === last - 3 &&
      cols0.EmailDateTime === last - 2 &&
      cols0.RowAddedAt === last - 1 &&
      cols0.LastUpdatedAt === last
    );

    // Normalize header spellings to exact desired labels.
    _canonicalizeHeaderCell_(cols0.ReviewStatus, 'ReviewStatus');
    _canonicalizeHeaderCell_(cols0.OutageID, 'OutageID');
    _canonicalizeHeaderCell_(cols0.EmailID, 'EmailID');
    _canonicalizeHeaderCell_(cols0.EmailDateTime, 'EmailDateTime');
    _canonicalizeHeaderCell_(cols0.RowAddedAt, 'RowAddedAt');
    _canonicalizeHeaderCell_(cols0.LastUpdatedAt, 'LastUpdatedAt');

    try {
      sheet.setFrozenRows(1);
    } catch (e) {
      // ignore
    }
    try {
      if (orderedAtEnd) {
        sheet.getRange(1, cols0.ReviewStatus, 1, 4).setFontWeight('bold');
      }
    } catch (e) {
      // ignore
    }

    if (orderedAtEnd) {
      return {
        statusCol: cols0.ReviewStatus,
        createdHeaders: false,
        auditCols: {
          ReviewStatus: cols0.ReviewStatus,
          OutageID: cols0.OutageID,
          EmailID: cols0.EmailID,
          EmailDateTime: cols0.EmailDateTime,
          RowAddedAt: cols0.RowAddedAt,
          LastUpdatedAt: cols0.LastUpdatedAt,
        },
      };
    }
  }

  // Otherwise, create a fresh trailing audit block and migrate values from any existing columns.
  const existingCols = cols0;

  const currentLast = sheet.getLastColumn();
  try {
    sheet.insertColumnsAfter(currentLast > 0 ? currentLast : 1, desired.length);
  } catch (e) {
    // If insert fails (protected), abort.
    return null;
  }

  const destStart = currentLast + 1;
  try {
    sheet.getRange(1, destStart, 1, desired.length).setValues([desired]).setFontWeight('bold');
  } catch (e) {
    return null;
  }

  try {
    sheet.setFrozenRows(1);
  } catch (e) {
    // ignore
  }

  const maxRows = sheet.getMaxRows();
  const dataRows = Math.max(0, maxRows - 1);
  if (dataRows > 0) {
    const mapping = [
      { from: existingCols.ReviewStatus, toOffset: 0 },
      { from: existingCols.OutageID, toOffset: 1 },
      { from: existingCols.EmailID, toOffset: 2 },
      { from: existingCols.EmailDateTime, toOffset: 3 },
      { from: existingCols.RowAddedAt, toOffset: 4 },
      { from: existingCols.LastUpdatedAt, toOffset: 5 },
    ];
    mapping.forEach(m => {
      if (!m.from) return;
      try {
        const values = sheet.getRange(2, m.from, dataRows, 1).getValues();
        sheet.getRange(2, destStart + m.toOffset, dataRows, 1).setValues(values);
      } catch (e) {
        // ignore
      }
    });
  }

  // Delete old columns for these audit headers (right-to-left so indices remain valid).
  const toDelete = [existingCols.ReviewStatus, existingCols.OutageID, existingCols.EmailID, existingCols.EmailDateTime, existingCols.RowAddedAt, existingCols.LastUpdatedAt]
    .filter(c => !!c)
    .sort((a, b) => b - a);
  toDelete.forEach(colIdx => {
    try { sheet.deleteColumn(colIdx); } catch (e) { /* ignore */ }
  });

  // Recompute positions after deletion.
  const newLastCol = sheet.getLastColumn();
  const newHeaders = (sheet.getLastRow() >= 1 && newLastCol >= 1)
    ? sheet.getRange(1, 1, 1, newLastCol).getValues()[0]
    : [];
  const cols = _findCanonicalCols_(newHeaders);
  // Ensure exact spelling on the new header block.
  _canonicalizeHeaderCell_(cols.ReviewStatus, 'ReviewStatus');
  _canonicalizeHeaderCell_(cols.OutageID, 'OutageID');
  _canonicalizeHeaderCell_(cols.EmailID, 'EmailID');
  _canonicalizeHeaderCell_(cols.EmailDateTime, 'EmailDateTime');
  _canonicalizeHeaderCell_(cols.RowAddedAt, 'RowAddedAt');
  _canonicalizeHeaderCell_(cols.LastUpdatedAt, 'LastUpdatedAt');

  return {
    statusCol: cols.ReviewStatus,
    createdHeaders: true,
    auditCols: {
      ReviewStatus: cols.ReviewStatus,
      OutageID: cols.OutageID,
      EmailID: cols.EmailID,
      EmailDateTime: cols.EmailDateTime,
      RowAddedAt: cols.RowAddedAt,
      LastUpdatedAt: cols.LastUpdatedAt,
    },
  };
}

function removeReviewStatusTrigger() {
  _removeInstallableTriggers_('handleReviewStatusEdit_');
  SpreadsheetApp.getUi().alert('Removed ReviewStatus onEdit trigger.');
}

/**
 * Installable onEdit handler.
 * Clears highlight when ReviewStatus changes away from Pending.
 */
function handleReviewStatusEdit_(e) {
  try {
    if (!e || !e.range) return;

    const sheet = e.range.getSheet();
    if (!sheet) return;

    const isReviewQueue = !!(CONFIG && CONFIG.SHEETS && sheet.getName && sheet.getName() === CONFIG.SHEETS.REVIEW_QUEUE);
    const reviewQueueEnabled = !!(CONFIG && CONFIG.FEATURES && CONFIG.FEATURES.REVIEW_QUEUE_ENABLED);

    // Review Queue propagation should happen for ANY edits on [Review Queue].
    if (isReviewQueue && reviewQueueEnabled) {
      try { if (typeof propagateModifications === 'function') propagateModifications(e); } catch (ignore) {}
    }

    // Skip excluded sheets (use the same list as the installer).
    if (!_isEligibleSheetForReviewStatus_(sheet)) return;

    const statusCol = _findReviewStatusColumnIndex_(sheet);
    if (!statusCol) return;

    const range = e.range;
    const startCol = range.getColumn();
    const endCol = startCol + range.getNumColumns() - 1;

    // Only react when edits touch the ReviewStatus column.
    if (statusCol < startCol || statusCol > endCol) {
      return;
    }

    const startRow = range.getRow();
    const numRows = range.getNumRows();

    // Determine which column within the edited range corresponds to ReviewStatus.
    const statusOffset = statusCol - startCol;
    const values = range.getValues();

    const lastCol = Math.max(1, sheet.getLastColumn());

    const pendingNorm = String(CONFIG.REVIEW_STATUS.PENDING || 'Pending').trim().toLowerCase();

    for (let r = 0; r < numRows; r++) {
      const rowIndex = startRow + r;
      if (rowIndex < 2) continue;

      const cellValue = (values[r] && values[r][statusOffset] != null) ? values[r][statusOffset] : '';
      const norm = String(cellValue || '').trim().toLowerCase();

      const rowRange = sheet.getRange(rowIndex, 1, 1, lastCol);

      if (norm === pendingNorm) {
        // Match backend highlight color (#FFF3CD) so UI is consistent.
        rowRange.setBackground('#FFF3CD');
      } else {
        // Remove background highlight. (This resets the background formatting.)
        rowRange.setBackground(null);
      }
    }

    // After a status edit, optionally auto-remove reviewed items from [Review Queue].
    if (isReviewQueue && reviewQueueEnabled) {
      try { if (typeof autoRemoveReviewedRecords === 'function') autoRemoveReviewedRecords(e); } catch (ignore) {}
    }

    // Keep BigQuery-consolidated aligned when statuses change on either source sheets
    // or [Review Queue], including rejected -> approved recoveries.
    try { if (typeof consolidateAllSimple === 'function') consolidateAllSimple(); } catch (ignore) {}
  } catch (err) {
    // Avoid throwing in triggers.
    try { Logger.log('handleReviewStatusEdit_ failed: ' + err); } catch (ignore) {}
  }
}

function _isEligibleSheetForReviewStatus_(sheet) {
  if (!sheet) return false;
  const name = sheet.getName();
  const excludeSet = _buildReviewStatusExcludeSet_();
  return !excludeSet.has(name);
}

function _findReviewStatusColumnIndex_(sheet) {
  const lastCol = sheet.getLastColumn();
  if (lastCol < 1) return null;

  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];

  // Only apply dropdowns when we can positively identify the ReviewStatus header.
  // This avoids accidentally targeting unrelated columns (e.g., FailedTime in column C).
  for (let i = 0; i < headers.length; i++) {
    const raw = headers[i];
    const key = _normalizeHeaderKey_(raw);
    if (key === 'reviewstatus' || key === 'reviewerstatus') {
      return i + 1; // 1-based
    }
  }

  return null;
}

function _normalizeHeaderKey_(v) {
  return String(v || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/_/g, '');
}

function _buildReviewStatusExcludeSet_() {
  let exclude = [];
  try {
    if (typeof getConsolidationExcludeSheets_ === 'function') {
      exclude = exclude.concat(getConsolidationExcludeSheets_() || []);
    }
  } catch (e) {
    // ignore
  }

  try {
    if (typeof EXCLUDED_SHEETS !== 'undefined' && EXCLUDED_SHEETS && EXCLUDED_SHEETS.length) {
      exclude = exclude.concat(EXCLUDED_SHEETS);
    }
  } catch (e) {
    // ignore
  }

  const set = new Set(exclude.map(x => String(x || '').trim()).filter(Boolean));

  // [Review Queue] should be eligible for the ReviewStatus onEdit handler,
  // even though it is excluded from consolidation and other processing.
  try {
    const rq = CONFIG && CONFIG.SHEETS && CONFIG.SHEETS.REVIEW_QUEUE;
    if (rq) set.delete(rq);
  } catch (e) {
    // ignore
  }

  // Also remove common naming variants.
  ['[Review Queue]', 'Review Queue', 'ReviewQueue', 'review queue', 'reviewqueue'].forEach(n => {
    try { set.delete(n); } catch (e) { /* ignore */ }
  });

  return set;
}

function _getEligibleSheetsForReviewStatus_(ss) {
  const spreadsheet = ss || SpreadsheetApp.getActiveSpreadsheet();
  const all = spreadsheet.getSheets();

  const excludeSet = _buildReviewStatusExcludeSet_();
  return all.filter(sh => !excludeSet.has(sh.getName()));
}

function _ensureInstallableTrigger_(handlerFunctionName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const triggers = ScriptApp.getProjectTriggers();

  // If already present, do nothing.
  for (let i = 0; i < triggers.length; i++) {
    const t = triggers[i];
    if (t.getHandlerFunction && t.getHandlerFunction() === handlerFunctionName) {
      return;
    }
  }

  ScriptApp.newTrigger(handlerFunctionName).forSpreadsheet(ss).onEdit().create();
}

function _removeInstallableTriggers_(handlerFunctionName) {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(t => {
    try {
      if (t.getHandlerFunction && t.getHandlerFunction() === handlerFunctionName) {
        ScriptApp.deleteTrigger(t);
      }
    } catch (e) {
      // ignore
    }
  });
}
