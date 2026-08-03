/**
 * Refreshes the Review Queue with unreviewed emails
 * Scans all sheets (except excluded ones) and finds all emails
 * where reviewer status is Pending or Auto-Synced
 */
function refreshReviewQueue() {
  const enabled = !!(CONFIG && CONFIG.FEATURES && CONFIG.FEATURES.REVIEW_QUEUE_ENABLED);
  if (!enabled) {
    SheetUtils.showAlert('Review Queue is disabled.');
    return;
  }

  // Ensure [Review Queue] headers are present before any data is written
  ensureReviewQueueHeaders();

  const sheets = SheetUtils.getNonExcludedSheets();
  const emailsWithDates = collectUnreviewedEmails(sheets);

  // Sort by date (oldest first)
  emailsWithDates.sort((a, b) => a.date - b.date);

  // Show all unreviewed emails (no limit)
  const emailRows = emailsWithDates.map(item => item.row);

  // Write to Review Queue sheet
  writeToReviewQueue(emailRows);
}

/**
 * Collects all unreviewed emails with valid dates from sheets
 * @private
 */
function collectUnreviewedEmails(sheets) {
  const emailsWithDates = [];
  // Normalize into the current [Review Queue] schema so headers stay consistent with system tabs.
  // (ensureReviewQueueHeaders() already ran in refreshReviewQueue().)
  let canonicalHeaders = [];
  try {
    const reviewQueue = SheetUtils.getOrCreateSheet(CONFIG.SHEETS.REVIEW_QUEUE);
    canonicalHeaders = getSheetHeaders(reviewQueue);
  } catch (e) {
    canonicalHeaders = [];
  }

  if (!canonicalHeaders || !canonicalHeaders.length) {
    canonicalHeaders = [
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
  }

  function normalizeHeaderKey(v) {
    return String(v || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/_/g, '');
  }

  function buildHeaderIndex(headers) {
    const idx = {};
    (headers || []).forEach((h, i) => {
      const key = normalizeHeaderKey(h);
      if (!key) return;
      if (idx[key] == null) idx[key] = i;
    });
    return idx;
  }

  function resolveIndex(headerIndex, headerName) {
    const key = normalizeHeaderKey(headerName);
    if (!key) return null;

    // Synonyms / legacy support.
    if (key === 'reviewstatus') {
      return headerIndex['reviewstatus'] != null ? headerIndex['reviewstatus'] : headerIndex['reviewerstatus'];
    }
    if (key === 'emaildatetime' || key === 'emailtimestamp') {
      return headerIndex['emaildatetime'] != null
        ? headerIndex['emaildatetime']
        : headerIndex['emailtimestamp'];
    }

    return headerIndex[key];
  }

  function coerceNullableNonNegativeInt(v) {
    if (v == null || v === '') return '';
    if (typeof v === 'number' && isFinite(v)) {
      if (v < 0) return '';
      if (Number.isInteger(v)) return v;
      // If it's a float, keep it only if it's effectively an int.
      const asInt = Math.trunc(v);
      return asInt === v ? asInt : '';
    }

    const s = String(v).trim();
    if (!s) return '';
    // Accept plain integer strings (e.g. "12").
    if (!/^[-+]?\d+$/.test(s)) return '';
    const n = Number(s);
    if (!isFinite(n) || n < 0) return '';
    return Math.trunc(n);
  }

  function formatDateTimeParts(v) {
    if (v == null || v === '') {
      return { date: '', time: '' };
    }
    const d = (v instanceof Date) ? v : new Date(v);
    if (isNaN(d.getTime())) {
      return { date: '', time: '' };
    }
    // Sheets time-only values often serialize to year 1899; treat as blank.
    if (d.getFullYear && d.getFullYear() === 1899) {
      return { date: '', time: '' };
    }
    const tz = Session.getScriptTimeZone();
    return {
      date: Utilities.formatDate(d, tz, 'yyyy-MM-dd'),
      time: Utilities.formatDate(d, tz, 'HH:mm:ss')
    };
  }

  function normalizeRowToCanonical(row, headerIndex) {
    function cell(header) {
      const idx = resolveIndex(headerIndex, header);
      if (idx == null) return '';
      return idx < row.length ? row[idx] : '';
    }

    // Support legacy timestamp-only sheets by splitting TimeStamp into Date + Time.
    const failedTs = cell('FailedTimeStamp');
    const resumedTs = cell('ResumedTimeStamp');
    const repairedTs = cell('RepairedTimeStamp');

    const failedParts = formatDateTimeParts(failedTs);
    const resumedParts = formatDateTimeParts(resumedTs);
    const repairedParts = formatDateTimeParts(repairedTs);

    // Prefer explicit Date/Time columns if present; otherwise use derived parts.
    const failedDate = cell('FailedDate') || failedParts.date;
    const failedTime = cell('FailedTime') || failedParts.time;
    const resumedDate = cell('ResumedDate') || resumedParts.date;
    const resumedTime = cell('ResumedTime') || resumedParts.time;
    const repairedDate = cell('RepairedDate') || repairedParts.date;
    const repairedTime = cell('RepairedTime') || repairedParts.time;

    const out = [];
    canonicalHeaders.forEach(h => {
      if (h === 'FailedDate') return out.push(failedDate);
      if (h === 'FailedTime') return out.push(failedTime);
      if (h === 'ResumedDate') return out.push(resumedDate);
      if (h === 'ResumedTime') return out.push(resumedTime);
      if (h === 'RepairedDate') return out.push(repairedDate);
      if (h === 'RepairedTime') return out.push(repairedTime);
      if (h === 'DownTime_mins' || h === 'Total_No__of_ccts' || h === 'No__of_NR') {
        return out.push(coerceNullableNonNegativeInt(cell(h)));
      }
      return out.push(cell(h));
    });
    return out;
  }

  function hasMinimumSignal(row, headerIndex) {
    function cell(header) {
      const idx = resolveIndex(headerIndex, header);
      if (idx == null || idx >= row.length) return '';
      return String(row[idx] || '').trim();
    }

    const system = cell('System');
    if (!system || system.toLowerCase() === 'unknown') return false;

    const outageId = cell('OutageID');
    if (outageId) return true;

    const failedDate = cell('FailedDate');
    const failedTime = cell('FailedTime');
    const segment = cell('Segment');
    const reason = cell('Reason');
    const recovery = cell('RecoveryProgress');

    return !!((failedDate || failedTime) && (segment || reason || recovery));
  }
  
  sheets.forEach(sheet => {
    try {
      if (typeof _ensureReviewAuditHeaders_ === 'function') {
        _ensureReviewAuditHeaders_(sheet);
      }
    } catch (e) {
      // Continue even if header migration fails on one tab.
    }

    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    
    if (lastRow < 2) return;
    
    const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0]
      .map(h => String(h || '').trim());
    const headerIndex = buildHeaderIndex(headers);

    const data = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
    
    data.forEach(row => {
      // ReviewStatus can move around depending on schema; prefer header mapping.
      const reviewStatusCol = resolveIndex(headerIndex, 'ReviewStatus');
      const reviewStatusRaw = (
        reviewStatusCol != null
          ? row[reviewStatusCol]
          : row[CONFIG.COLUMNS.OUTAGE.REVIEW_STATUS - 1]
      );
      const reviewStatus = String(reviewStatusRaw || '');
      
      // Include only Pending and Auto-Synced records
      if (reviewStatus !== CONFIG.REVIEW_STATUS.PENDING && 
          reviewStatus !== CONFIG.REVIEW_STATUS.AUTO_SYNCED) {
        return;
      }

      if (!hasMinimumSignal(row, headerIndex)) {
        return;
      }
      
      // Parse and validate date
      const emailDateCol = resolveIndex(headerIndex, 'EmailDateTime');
      const dateValue = (
        emailDateCol != null
          ? row[emailDateCol]
          : row[CONFIG.COLUMNS.OUTAGE.EMAIL_TIMESTAMP - 1]
      );
      const parsedDate = new Date(dateValue);
      
      if (isNaN(parsedDate.getTime())) {
        return; // Skip invalid dates
      }

      const canonicalRow = normalizeRowToCanonical(row, headerIndex);
      
      emailsWithDates.push({
        date: parsedDate,
        row: canonicalRow
      });
    });
  });
  
  return emailsWithDates;
}

/**
 * Writes email rows to the Review Queue sheet
 * @private
 */
function writeToReviewQueue(emailRows) {
  const reviewSheet = SheetUtils.getOrCreateSheet(CONFIG.SHEETS.REVIEW_QUEUE);

  const headers = getSheetHeaders(reviewSheet);
  function normalizeHeaderKey(v) {
    return String(v || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/_/g, '');
  }

  function buildHeaderIndexByKey(headersList) {
    const out = {};
    (headersList || []).forEach((h, i) => {
      const key = normalizeHeaderKey(h);
      if (!key) return;
      if (out[key] == null) out[key] = i;
    });
    return out;
  }

  function getCell(row, idx) {
    if (idx == null || idx < 0 || idx >= row.length) return '';
    return row[idx];
  }

  const headerIndex = buildHeaderIndexByKey(headers);
  const emailIdIdx = headerIndex.emailid;
  const rowAddedIdx = headerIndex.rowaddedat;
  const lastUpdatedIdx = headerIndex.lastupdatedat;

  const previousByEmailId = {};
  const lastRow = reviewSheet.getLastRow();
  const lastCol = Math.max(1, reviewSheet.getLastColumn());
  if (lastRow > 1 && emailIdIdx != null) {
    const existing = reviewSheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
    for (let i = 0; i < existing.length; i++) {
      const row = existing[i];
      const emailId = String(getCell(row, emailIdIdx) || '').trim();
      if (!emailId) continue;
      previousByEmailId[emailId] = {
        row: row,
        rowAddedAt: getCell(row, rowAddedIdx),
        lastUpdatedAt: getCell(row, lastUpdatedIdx)
      };
    }
  }

  function comparableRow(row) {
    const out = [];
    for (let i = 0; i < row.length; i++) {
      if (i === rowAddedIdx || i === lastUpdatedIdx) continue;
      out.push(String(row[i] == null ? '' : row[i]));
    }
    return out.join('\u001f');
  }
  
  // Clear existing data (preserve headers)
  SheetUtils.clearDataRows(reviewSheet);
  
  // Write new data
  if (emailRows.length > 0) {
    // Normalize row widths to the Review Queue header width.
    // Rows from different source sheets can have different column counts (e.g., 18 vs 19),
    // and Sheets will throw if any row width doesn't match the target range.
    const targetCols = Math.max(1, reviewSheet.getLastColumn());
    const now = new Date();
    const normalized = emailRows.map(r => {
      const out = new Array(targetCols).fill('');
      const n = Math.min(targetCols, (r || []).length);
      for (let i = 0; i < n; i++) out[i] = r[i];

      if (emailIdIdx != null && (rowAddedIdx != null || lastUpdatedIdx != null)) {
        const emailId = String(getCell(out, emailIdIdx) || '').trim();
        const prev = emailId ? previousByEmailId[emailId] : null;

        if (rowAddedIdx != null) {
          out[rowAddedIdx] = prev && prev.rowAddedAt ? prev.rowAddedAt : now;
        }

        if (lastUpdatedIdx != null) {
          if (!prev || !prev.row) {
            out[lastUpdatedIdx] = now;
          } else {
            const changed = comparableRow(out) !== comparableRow(prev.row);
            out[lastUpdatedIdx] = changed ? now : (prev.lastUpdatedAt || now);
          }
        }
      }

      return out;
    });

    reviewSheet
      .getRange(2, 1, normalized.length, targetCols)
      .setValues(normalized);

    try {
      if (rowAddedIdx != null) {
        reviewSheet.getRange(2, rowAddedIdx + 1, normalized.length, 1).setNumberFormat('yyyy-mm-dd hh:mm:ss');
      }
      if (lastUpdatedIdx != null) {
        reviewSheet.getRange(2, lastUpdatedIdx + 1, normalized.length, 1).setNumberFormat('yyyy-mm-dd hh:mm:ss');
      }
    } catch (e) {
      // ignore format failures
    }
  }
}

/**
 * Auto-remove reviewed records from Review Queue
 * Called when status changes to Approved, Modified, or Rejected
 * Supports multi-row edits (e.g., copy-paste to multiple rows)
 *
 * @param {Object} e - Edit event object from onEdit trigger
 */
function autoRemoveReviewedRecords(e) {
	if (!CONFIG.REVIEW.AUTO_REMOVE_REVIEWED) return;

	const sheet = e.range.getSheet();

	// Only process edits in Review Queue
	if (sheet.getName() !== CONFIG.SHEETS.REVIEW_QUEUE) return;

  // Only process if status column is affected
  const range = e.range;
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0]
    .map(h => String(h || '').trim());
  let statusColIndex = headers.indexOf('ReviewStatus') + 1;
  if (!statusColIndex) statusColIndex = CONFIG.COLUMNS.OUTAGE.REVIEW_STATUS;
	const rangeStartCol = range.getColumn();
	const rangeEndCol = rangeStartCol + range.getNumColumns() - 1;

	// Check if status column is within the edited range
	if (statusColIndex < rangeStartCol || statusColIndex > rangeEndCol) return;

	const startRow = range.getRow();
	const numRows = range.getNumRows();

	// Process all edited rows in reverse order (to avoid row index shifting)
	const rowsToDelete = [];
	for (let r = 0; r < numRows; r++) {
		const editedRow = startRow + r;
		if (editedRow < 2) continue; // Skip header row

    const newValue = String(sheet.getRange(editedRow, statusColIndex).getValue() || '').trim();
    const newValueNorm = newValue.toLowerCase();

		// Check if status is reviewed (not Pending or Auto-Synced)
    if (newValueNorm === String(CONFIG.REVIEW_STATUS.APPROVED).toLowerCase() ||
        newValueNorm === String(CONFIG.REVIEW_STATUS.MODIFIED).toLowerCase() ||
        newValueNorm === String(CONFIG.REVIEW_STATUS.REJECTED).toLowerCase()) {
			rowsToDelete.push(editedRow);
		}
	}

	// Delete rows in reverse order to avoid row index shifting issues
	for (let i = rowsToDelete.length - 1; i >= 0; i--) {
		sheet.deleteRow(rowsToDelete[i]);
	}
}

/**
 * Propagates changes from Review Queue to source sheets
 * When a record is edited in Review Queue, find and update the matching record in source sheets
 * Supports multi-row edits (e.g., copy-paste to multiple rows)
 * @param {Object} e - Edit event object from onEdit trigger
 */
function propagateModifications(e) {
  const sheet = e.range.getSheet();
  
  // Only process edits in Review Queue
  if (sheet.getName() !== CONFIG.SHEETS.REVIEW_QUEUE) return;
  
  const range = e.range;
  const startRow = range.getRow();
  const numRows = range.getNumRows();
  const lastCol = sheet.getLastColumn();
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];

  function normalizeHeaderKey(v) {
    return String(v || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/_/g, '');
  }

  const headerKeys = headers.map(normalizeHeaderKey);
  const emailIdCol = (function() {
    for (let i = 0; i < headerKeys.length; i++) {
      if (headerKeys[i] === 'emailid' || headerKeys[i] === 'emailids') return i + 1;
    }
    return CONFIG.COLUMNS.OUTAGE.EMAIL_ID;
  })();
  
  if (startRow < 2) return; // Skip header row
  
  // Process all rows in the edited range (handles multi-row copy-paste)
  for (let r = 0; r < numRows; r++) {
    const editedRow = startRow + r;
    
    // Get the EmailID from the edited row
    const emailId = sheet.getRange(editedRow, emailIdCol).getValue();
    if (!emailId) continue;
    
    // Get all values from the edited row
    const editedRowData = sheet.getRange(editedRow, 1, 1, lastCol).getValues()[0];

    // Keyed map of values by normalized header key (preserves blanks).
    const updatedByKey = {};
    for (let c = 0; c < headerKeys.length; c++) {
      const key = headerKeys[c];
      if (!key) continue;
      updatedByKey[key] = editedRowData[c];
    }
    
    // Find and update matching records in source sheets
    const sourceSheets = SheetUtils.getNonExcludedSheets();
    
    sourceSheets.forEach(sourceSheet => {
      updateMatchingRecordInSheet(sourceSheet, emailId, updatedByKey);
    });
  }
}

/**
 * Updates a matching record in a specific sheet
 * @private
 */
function updateMatchingRecordInSheet(sourceSheet, emailId, updatedByKey) {
  const lastRow = sourceSheet.getLastRow();
  if (lastRow < 2) return;

  const lastCol = sourceSheet.getLastColumn();
  if (lastCol < 1) return;

  function normalizeHeaderKey(v) {
    return String(v || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/_/g, '');
  }

  const headers = sourceSheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const headerKeys = headers.map(normalizeHeaderKey);

  function findColIndex(keys, candidates) {
    for (let i = 0; i < keys.length; i++) {
      if (!keys[i]) continue;
      if (candidates.indexOf(keys[i]) !== -1) return i + 1;
    }
    return null;
  }

  const emailIdCol = findColIndex(headerKeys, ['emailid', 'emailids']);
  if (!emailIdCol) return;
  
  // Get all EmailIDs from source sheet (header-based; supports trailing audit blocks)
  const emailIds = sourceSheet
    .getRange(2, emailIdCol, lastRow - 1, 1)
    .getValues()
    .flat();
  
  // Find matching row
  const matchingRowIndex = emailIds.findIndex(id => String(id).trim() === String(emailId).trim());
  if (matchingRowIndex === -1) return; // No match found
  
  const actualRow = matchingRowIndex + 2; // Convert to 1-based, accounting for header

  const existingRow = sourceSheet.getRange(actualRow, 1, 1, lastCol).getValues()[0];
  const rowAddedCol = findColIndex(headerKeys, ['rowaddedat']);
  const lastUpdatedCol = findColIndex(headerKeys, ['lastupdatedat']);

  function hasKey(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function resolveUpdatedValueForKey(key) {
    // ReviewStatus legacy
    if (key === 'reviewstatus' || key === 'reviewerstatus') {
      if (hasKey(updatedByKey, 'reviewstatus')) return updatedByKey['reviewstatus'];
      if (hasKey(updatedByKey, 'reviewerstatus')) return updatedByKey['reviewerstatus'];
      return undefined;
    }
    // Email datetime legacy
    if (key === 'emaildatetime' || key === 'emailtimestamp') {
      if (hasKey(updatedByKey, 'emaildatetime')) return updatedByKey['emaildatetime'];
      if (hasKey(updatedByKey, 'emailtimestamp')) return updatedByKey['emailtimestamp'];
      return undefined;
    }
    if (hasKey(updatedByKey, key)) return updatedByKey[key];
    return undefined;
  }

  // Update only columns present in the source sheet; preserve any extra columns.
  for (let c = 0; c < headerKeys.length; c++) {
    const key = headerKeys[c];
    if (!key) continue;
    if (key === 'rowaddedat' || key === 'lastupdatedat') continue;
    const v = resolveUpdatedValueForKey(key);
    if (v === undefined) continue;
    existingRow[c] = v;
  }

  // Maintain audit-style row lifecycle timestamps in source sheets.
  const now = new Date();
  if (rowAddedCol && !existingRow[rowAddedCol - 1]) {
    existingRow[rowAddedCol - 1] = now;
  }
  if (lastUpdatedCol) {
    existingRow[lastUpdatedCol - 1] = now;
  }

  sourceSheet.getRange(actualRow, 1, 1, lastCol).setValues([existingRow]);
}