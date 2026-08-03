/**
 * Loads email details from Gmail API via Cloud Run proxy
 * Fetches email IDs from [Email Details] sheet
 * Populates subject, sender, and body columns in [Email Details]
 */
function loadEmailDetails() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const detailsSheet = ss.getSheetByName(CONFIG.SHEETS.EMAIL_DETAILS);
  
  if (!detailsSheet) {
    SheetUtils.showAlert(`Sheet "${CONFIG.SHEETS.EMAIL_DETAILS}" not found.`);
    return;
  }

  // Ensure the tab has headers in row 1 and that any accidentally-entered
  // data in row 1 is moved down to row 2.
  ensureEmailDetailsHeaders_(detailsSheet);
  
  // Get email IDs from primary or fallback sheet
  const { emailIds, usedFallback } = getEmailIdsFromSheets(ss, detailsSheet);
  
  if (emailIds.length === 0) {
    SheetUtils.showAlert(CONFIG.MESSAGES.NO_IDS_FOUND);
    return;
  }
  
  // If IDs came from fallback, populate the [Email Details] EmailID column first
  // (keeps the tab aligned and makes it obvious which messages were requested)
  if (usedFallback && emailIds.length > 0) {
    const idRows = emailIds.map(id => [id || '']);
    detailsSheet.getRange(2, CONFIG.COLUMNS.EMAIL_DETAILS.EMAIL_ID, idRows.length, 1).setValues(idRows);
  }

  // Ask backend to fetch emails by ID and write into the sheet directly
  const updatedRows = loadEmailsIntoSheetFromBackend_(ss.getId(), emailIds);

  SheetUtils.showAlert(`Refreshed ${updatedRows} message(s).`);
}

function ensureEmailDetailsHeaders_(sheet) {
  try {
    if (!sheet) return;

    const expected = ['EmailID', 'Subject', 'Sender', 'Body'];
    const headerRange = sheet.getRange(1, 1, 1, expected.length);
    const row1 = headerRange.getValues()[0] || [];

    function norm(v) {
      return String(v || '').trim().toLowerCase().replace(/\s+/g, '');
    }

    const looksLikeHeaders = expected.every((h, i) => norm(row1[i]) === norm(h));
    if (looksLikeHeaders) return;

    // If row 1 contains data (often a message id pasted into A1), move it to row 2
    // to preserve the convention that row 1 is headers.
    const row1HasAnyValue = row1.some(v => String(v || '').trim() !== '');
    if (row1HasAnyValue) {
      const row2Range = sheet.getRange(2, 1, 1, expected.length);
      const row2 = row2Range.getValues()[0] || [];
      const row2IsEmpty = row2.every(v => String(v || '').trim() === '');
      if (row2IsEmpty) {
        row2Range.setValues([row1.map(v => v == null ? '' : v)]);
        headerRange.clearContent();
      }
    }

    // Write canonical headers.
    headerRange.setValues([expected]);
  } catch (e) {
    // Best-effort only; don't block Load Emails.
    try { Logger.log('ensureEmailDetailsHeaders_ failed: ' + e); } catch (ignore) {}
  }
}

/**
 * Gets email IDs from primary sheet or fallback
 * @private
 */
function getEmailIdsFromSheets(ss, primarySheet) {
  let emailIds = SheetUtils.getEmailIds(primarySheet, CONFIG.COLUMNS.EMAIL_DETAILS.EMAIL_ID);
  let usedFallback = false;

  // Review Queue fallback is feature-gated.
  // When enabled, allow fallback to [Review Queue] if [Email Details] is empty.
  const reviewQueueEnabled = !!(CONFIG && CONFIG.FEATURES && CONFIG.FEATURES.REVIEW_QUEUE_ENABLED);
  if (reviewQueueEnabled && emailIds.length === 0) {
    const fallbackSheet = ss.getSheetByName(CONFIG.SHEETS.REVIEW_QUEUE);
    if (fallbackSheet) {
      // [Review Queue] may have EmailID as a trailing audit column; locate it by header.
      let emailIdCol = null;
      try {
        const lastCol = fallbackSheet.getLastColumn();
        if (lastCol >= 1) {
          const headers = fallbackSheet.getRange(1, 1, 1, lastCol).getValues()[0] || [];
          for (let i = 0; i < headers.length; i++) {
            const key = String(headers[i] || '').trim().toLowerCase().replace(/\s+/g, '').replace(/_/g, '');
            if (key === 'emailid' || key === 'emailids') {
              emailIdCol = i + 1;
              break;
            }
          }
        }
      } catch (e) {
        // ignore
      }

      emailIds = SheetUtils.getEmailIds(fallbackSheet, emailIdCol || 1);
      usedFallback = true;
    }
  }
  
  return { emailIds, usedFallback };
}

/**
 * Fetches email data from Cloud Run backend
 * @private
 */
function loadEmailsIntoSheetFromBackend_(sheetId, emailIds) {
  const payload = JSON.stringify({
    sheetId: sheetId,
    messageIds: emailIds.slice(0, CONFIG.MAX_MESSAGE_IDS),
    includeBody: true,
    sheetName: CONFIG.SHEETS.EMAIL_DETAILS
  });

  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: payload,
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(CONFIG.CLOUD_RUN_BASE_URL + '/load_email_details', options);

  if (response.getResponseCode() !== 200) {
    SheetUtils.showAlert('Backend error: ' + response.getContentText());
    throw new Error('Backend request failed');
  }

  const data = JSON.parse(response.getContentText());
  return Number(data.updatedRows || 0);
}

/**
 * Writes email data to the sheet
 * @private
 */
