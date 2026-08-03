/**
 * Utility functions for common spreadsheet operations
 */

const SheetUtils = {
  /**
   * Gets or creates a sheet by name
   * @param {string} sheetName - Name of the sheet
   * @returns {Sheet} The sheet object
   */
  getOrCreateSheet(sheetName) {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(sheetName);
    
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }
    
    return sheet;
  },
  
  /**
   * Gets email IDs from a column in a sheet
   * @param {Sheet} sheet - The sheet to read from
   * @param {number} column - Column index (1-based)
   * @returns {Array<string>} Array of email IDs
   */
  getEmailIds(sheet, column) {
    if (column == null) {
      column = (CONFIG && CONFIG.COLUMNS && CONFIG.COLUMNS.OUTAGE && CONFIG.COLUMNS.OUTAGE.EMAIL_ID)
        || (CONFIG && CONFIG.COLUMNS && CONFIG.COLUMNS.EMAIL_DETAILS && CONFIG.COLUMNS.EMAIL_DETAILS.EMAIL_ID)
        || 1;
    }

    if (typeof column !== 'number' || !isFinite(column) || column < 1) {
      throw new Error('Invalid column index for getEmailIds: ' + column);
    }

    const lastRow = sheet.getLastRow();
    
    if (lastRow < 2) {
      return [];
    }
    
    const values = sheet
      .getRange(2, column, lastRow - 1, 1)
      .getValues()
      .flat()
      .map(v => v ? String(v).trim() : '')
      .filter(Boolean);
    
    return values;
  },
  
  /**
   * Clears data rows while preserving headers
   * @param {Sheet} sheet - The sheet to clear
   * @param {number} startRow - Starting row (default: 2)
   */
  clearDataRows(sheet, startRow = 2) {
    const maxRows = sheet.getMaxRows();
    const maxCols = sheet.getMaxColumns();
    
    if (maxRows >= startRow) {
      sheet
        .getRange(startRow, 1, maxRows - startRow + 1, maxCols)
        .clearContent();
    }
  },
  
  /**
   * Gets all sheets except excluded ones
   * @returns {Array<Sheet>} Array of sheet objects
   */
  getNonExcludedSheets() {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    return ss.getSheets().filter(sheet => 
      !EXCLUDED_SHEETS.includes(sheet.getName())
    );
  },
  
  /**
   * Shows an alert to the user
   * @param {string} message - Message to display
   */
  showAlert(message) {
    SpreadsheetApp.getUi().alert(message);
  }
};

/**
 * MIGRATION TOOL: Updates ReviewerStatus column to Review Status and sets blank cells to Pending
 * Run this ONCE after deployment to migrate existing data
 * Can be run from: Dev Tools menu or Script Editor
 */
function migrateReviewStatusColumn() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const allSheets = ss.getSheets();
  let updatedCount = 0;
  let rowsUpdated = 0;
  
  allSheets.forEach(sheet => {
    const sheetName = sheet.getName();
    
    // Skip [Email Details] sheet - it doesn't have Review Status column
    if (sheetName === CONFIG.SHEETS.EMAIL_DETAILS) return;
    
    const lastCol = sheet.getLastColumn();
    if (lastCol < 1) return;
    
    // Get header row
    const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
    
    // Find ReviewerStatus column (old name)
    let statusColIndex = headers.indexOf('ReviewerStatus');
    
    // If not found, try "ReviewStatus" or "Review Status" (already migrated)
    if (statusColIndex === -1) {
      statusColIndex = headers.indexOf('ReviewStatus');
    }
    if (statusColIndex === -1) {
      statusColIndex = headers.indexOf('Review Status');
    }
    
    if (statusColIndex !== -1) {
      // Update header to "ReviewStatus" (no space)
      sheet.getRange(1, statusColIndex + 1).setValue('ReviewStatus');
      
      const lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        const statusRange = sheet.getRange(2, statusColIndex + 1, lastRow - 1, 1);
        
        // Get current values
        const values = statusRange.getValues();
        
        // Map old values to new values and set blanks to Pending
        const updatedValues = values.map(row => {
          let currentValue = String(row[0]).trim();
          
          // Map old values to new values
          if (currentValue === 'OK') {
            return [CONFIG.REVIEW_STATUS.APPROVED];
          } else if (currentValue === 'Synced') {
            return [CONFIG.REVIEW_STATUS.AUTO_SYNCED];
          } else if (currentValue === '' || !currentValue) {
            return [CONFIG.REVIEW_STATUS.PENDING];
          }
          
          // Keep existing valid values
          return [row[0]];
        });
        
        statusRange.setValues(updatedValues);
        
        // Count updates
        const pendingCount = updatedValues.filter(row => row[0] === CONFIG.REVIEW_STATUS.PENDING).length;
        rowsUpdated += pendingCount;
        updatedCount++;
      }
    }
  });
  
  SpreadsheetApp.getUi().alert(
    `Migration Complete!\n\n` +
    `Updated ${updatedCount} sheet(s)\n` +
    `Set ${rowsUpdated} blank cells to "Pending"\n` +
    `Mapped old values (OK → Approved, Synced → Auto-Synced)`
  );
}

/**
 * Retrieves header row from a sheet
 * @param {Sheet} sheet - The sheet to read headers from
 * @returns {Array<string>} Array of header names
 */
function getSheetHeaders(sheet) {
  if (!sheet || sheet.getLastRow() < 1) {
    return [];
  }
  
  const headerRow = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  return headerRow.map(h => String(h || '').trim()).filter(Boolean);
}

/**
 * Sets header row in a sheet
 * @param {Sheet} sheet - The sheet to update
 * @param {Array<string>} headers - Array of header names
 */
function setSheetHeaders(sheet, headers) {
  if (!sheet || !headers || headers.length === 0) {
    return false;
  }
  
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  return true;
}

/**
 * Synchronizes headers to [Review Queue] from Config columns
 * Call this to ensure [Review Queue] has the correct schema headers
 * @returns {Object} Result with status and details
 */
function syncReviewQueueHeaders() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  function normalizeSheetName(name) {
    return String(name || '')
      .trim()
      .replace(/^\[\s*/,'')
      .replace(/\s*\]$/,'')
      .replace(/\s+/g,'')
      .toLowerCase();
  }

  function resolveOrCreateReviewQueueSheet() {
    const expectedName = CONFIG.SHEETS.REVIEW_QUEUE;
    let sheet = ss.getSheetByName(expectedName);
    if (sheet) return sheet;

    const expectedNorm = normalizeSheetName(expectedName);
    const candidates = ss.getSheets();

    // Try exact-ish variants first
    const variantNames = [
      '[Review Queue]',
      'Review Queue',
      'ReviewQueue',
      'review queue',
      'reviewqueue'
    ];
    for (const v of variantNames) {
      sheet = ss.getSheetByName(v);
      if (sheet) break;
    }

    // Fall back to normalized match
    if (!sheet) {
      for (const s of candidates) {
        if (normalizeSheetName(s.getName()) === expectedNorm) {
          sheet = s;
          break;
        }
      }
    }

    // If found under a different name, rename to the canonical name
    if (sheet && sheet.getName() !== expectedName) {
      try {
        sheet.setName(expectedName);
      } catch (e) {
        // If rename fails (name conflict), keep the found sheet name.
      }
      return sheet;
    }

    // As a last resort, create it (better than hard-failing)
    return SheetUtils.getOrCreateSheet(expectedName);
  }

  function normalizeHeaderKey_(v) {
    return String(v || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/_/g, '')
      .replace(/[^a-z0-9]/g, '');
  }

  function looksLikeSystemTabHeaders_(headers) {
    const keys = (headers || []).map(normalizeHeaderKey_).filter(Boolean);
    if (!keys.length) return false;
    const hasSystem = keys.indexOf('system') !== -1;
    const hasFailedDate = keys.indexOf('faileddate') !== -1;
    const hasReviewStatus = keys.indexOf('reviewstatus') !== -1 || keys.indexOf('reviewerstatus') !== -1;
    // System tabs usually have System + time split fields, plus (often) trailing audit block.
    return hasSystem && (hasFailedDate || hasReviewStatus);
  }

  function getSystemTabCanonicalHeaders_() {
    // Prefer using a real system tab header row as the canonical schema.
    // This keeps [Review Queue] aligned with whatever the backend/system tabs currently use.
    const exclude = new Set();
    try {
      if (typeof getConsolidationExcludeSheets_ === 'function') {
        (getConsolidationExcludeSheets_() || []).forEach(n => exclude.add(String(n || '').trim()));
      }
    } catch (e) {
      // ignore
    }

    // Always exclude internal bracketed/helper tabs.
    exclude.add(CONFIG.SHEETS.EMAIL_DETAILS);
    exclude.add(CONFIG.SHEETS.REVIEW_QUEUE);
    exclude.add(CONFIG.AUDIT.SHADOW_SHEET_NAME);

    const sheets = ss.getSheets();
    for (let i = 0; i < sheets.length; i++) {
      const sh = sheets[i];
      const name = String(sh.getName() || '').trim();
      if (!name) continue;
      if (exclude.has(name)) continue;
      if (name.toLowerCase() === '_auditshadow') continue;
      if (name.startsWith('[') && name.endsWith(']')) continue;

      const lastCol = sh.getLastColumn();
      if (lastCol < 1) continue;
      const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0]
        .map(h => String(h || '').trim());

      // Trim trailing empty header cells (common when users format extra columns).
      while (headers.length > 0 && String(headers[headers.length - 1] || '').trim() === '') {
        headers.pop();
      }

      const any = headers.some(h => String(h || '').trim() !== '');
      if (!any) continue;
      if (!looksLikeSystemTabHeaders_(headers)) continue;
      return headers;
    }

    return null;
  }

  const reviewQueue = resolveOrCreateReviewQueueSheet();

  const systemCanonical = getSystemTabCanonicalHeaders_();

  // Canonical headers for [Review Queue] should match system tabs.
  // If we cannot find a system tab, fall back to a minimal known-good schema.
  const canonicalHeaders = (systemCanonical && systemCanonical.length)
    ? systemCanonical
    : [
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
      // Accept either "Service Impact" or "Service_Impact" via normalization elsewhere.
      'Service Impact',
      'NoOfCircuits',
      'NoNonRestored',
      'RemedyTicket',
      // Trailing audit block
      'ReviewStatus',
      'OutageID',
      'EmailID',
      'EmailDateTime',
      'RowAddedAt',
      'LastUpdatedAt'
    ];

  // Review Queue-specific metadata columns are always required even if source tabs do not contain them.
  if (canonicalHeaders.indexOf('RowAddedAt') === -1) canonicalHeaders.push('RowAddedAt');
  if (canonicalHeaders.indexOf('LastUpdatedAt') === -1) canonicalHeaders.push('LastUpdatedAt');

  const optionalTrailing = [];

  function hasLegacyTimestampHeaders(headers) {
    const set = new Set((headers || []).map(h => String(h || '').trim()));
    return set.has('FailedTimeStamp') && set.has('ResumedTimeStamp') && set.has('RepairedTimeStamp');
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

  function migrateLegacySchema(sheet, currentHeaders) {
    const headerIndex = {};
    currentHeaders.forEach((h, i) => { headerIndex[String(h).trim()] = i; });

    const extras = optionalTrailing.filter(h => currentHeaders.indexOf(h) !== -1);
    const newHeaders = canonicalHeaders.concat(extras);

    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    const numRows = Math.max(0, lastRow - 1);

    const data = numRows > 0
      ? sheet.getRange(2, 1, numRows, lastCol).getValues()
      : [];

    function cell(row, header) {
      const idx = headerIndex[header];
      if (idx == null) return '';
      return (idx < row.length) ? row[idx] : '';
    }

    const migrated = data.map(row => {
      const failed = formatDateTimeParts(cell(row, 'FailedTimeStamp'));
      const resumed = formatDateTimeParts(cell(row, 'ResumedTimeStamp'));
      const repaired = formatDateTimeParts(cell(row, 'RepairedTimeStamp'));

      return newHeaders.map(h => {
        if (h === 'EmailDateTime') return cell(row, 'EmailDateTime') || cell(row, 'EmailTimeStamp');
        if (h === 'FailedDate') return failed.date;
        if (h === 'FailedTime') return failed.time;
        if (h === 'ResumedDate') return resumed.date;
        if (h === 'ResumedTime') return resumed.time;
        if (h === 'RepairedDate') return repaired.date;
        if (h === 'RepairedTime') return repaired.time;
        return cell(row, h);
      });
    });

    // Clear used range then write headers + migrated data
    if (lastRow > 0 && lastCol > 0) {
      sheet.getRange(1, 1, lastRow, lastCol).clearContent();
    }
    setSheetHeaders(sheet, newHeaders);
    if (migrated.length > 0) {
      sheet.getRange(2, 1, migrated.length, newHeaders.length).setValues(migrated);
    }

    return {
      success: true,
      message: `Migrated legacy schema to canonical headers` ,
      prevCount: currentHeaders.length,
      newCount: newHeaders.length,
      previousHeaders: currentHeaders,
      newHeaders: newHeaders
    };
  }
  
  // Get current headers
  const currentHeaders = getSheetHeaders(reviewQueue);

  // Legacy schema: migrate data instead of just overwriting headers
  if (currentHeaders.length > 0 && hasLegacyTimestampHeaders(currentHeaders)) {
    return migrateLegacySchema(reviewQueue, currentHeaders);
  }
  
  if (currentHeaders.length === 0) {
    // No headers - set them from expected
    setSheetHeaders(reviewQueue, canonicalHeaders);
    return {
      success: true,
      message: `Set headers for [Review Queue]: ${canonicalHeaders.length} columns`,
      prevCount: 0,
      newCount: canonicalHeaders.length
    };
  }
  
  // Check if headers match (order matters)
  // Preserve any optional trailing columns if they exist in the current sheet.
  const extras = optionalTrailing.filter(h => currentHeaders.indexOf(h) !== -1);
  const expectedHeaders = canonicalHeaders.concat(extras);

  const headersMatch = currentHeaders.length === expectedHeaders.length &&
    currentHeaders.every((h, i) => String(h) === String(expectedHeaders[i]));
  
  if (headersMatch) {
    return {
      success: true,
      prevCount: currentHeaders.length,
      newCount: expectedHeaders.length
    };
  }
  
  // Headers don't match - update them.
  // Review Queue is a derived sheet; to avoid mismatched columns, clear data rows on header update.
  setSheetHeaders(reviewQueue, expectedHeaders);
  try {
    SheetUtils.clearDataRows(reviewQueue);
  } catch (e) {
    // ignore
  }
  return {
    success: true,
    message: `Updated [Review Queue] headers`,
    prevCount: currentHeaders.length,
    newCount: expectedHeaders.length,
    previousHeaders: currentHeaders,
    newHeaders: expectedHeaders
  };
}

/**
 * Manual trigger to ensure all sheet headers are correct
 * Can be called from: Dev Tools menu or Script Editor
 * Run this if [Review Queue] headers are missing or incorrect
 */
function ensureReviewQueueHeaders() {
  const result = syncReviewQueueHeaders();

  if (!result.success) {
    const message = `Header Sync Result\n\n` +
      `Status: FAILED\n` +
      `Message: ${result.message}\n` +
      `Columns: ${result.prevCount} → ${result.newCount}\n\n` +
      (result.previousHeaders ? `Previous: ${result.previousHeaders.join(', ')}\n` : '') +
      (result.newHeaders ? `New: ${result.newHeaders.join(', ')}` : '');
    SpreadsheetApp.getUi().alert(message);
  }
}
