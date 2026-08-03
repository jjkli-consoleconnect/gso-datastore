/**
 * Dev tool: Generate OutageID in-sheet using the same normalization rules
 * as the backend `gmail-sheet-proxy/app.py::_build_outage_id_from_fields`.
 *
 * Safety:
 * - Operates ONLY on the current selection.
 * - Writes ONLY when the target OutageID cell is blank.
 * - Prompts for confirmation before writing.
 */

function devGenerateOutageIdForSelection() {
  const ui = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSheet();
  if (!sheet) {
    ui.alert('No active sheet.');
    return;
  }

  // Avoid operating on excluded sheets.
  const excludeSet = _buildOutageIdExcludeSet_();
  if (excludeSet.has(sheet.getName())) {
    ui.alert('This sheet is excluded from Dev tools: ' + sheet.getName());
    return;
  }

  const range = sheet.getActiveRange();
  if (!range) {
    ui.alert('Select one or more data rows first.');
    return;
  }

  const startRow = range.getRow();
  const numRows = range.getNumRows();
  if (numRows < 1) {
    ui.alert('Select one or more data rows first.');
    return;
  }

  const resolved = _resolveOutageIdColumns_(sheet);
  if (!resolved || !resolved.outageIdCol) {
    ui.alert('Could not find/create an OutageID column on this sheet.');
    return;
  }

  const outageIdCol = resolved.outageIdCol;
  const systemCol = resolved.systemCol;
  const segmentCol = resolved.segmentCol;
  const failedDateCol = resolved.failedDateCol;
  const failedTsCol = resolved.failedTsCol;
  const lastCol = resolved.lastCol;

  if (!systemCol || !segmentCol) {
    ui.alert('Missing required columns on this sheet.\n\nRequired headers: System, Segment');
    return;
  }

  // Clamp selection to data rows only.
  const dataStartRow = Math.max(2, startRow);
  const dataEndRow = startRow + numRows - 1;
  if (dataEndRow < 2) {
    ui.alert('Select one or more data rows (row 2+).');
    return;
  }
  const dataNumRows = dataEndRow - dataStartRow + 1;

  const block = sheet.getRange(dataStartRow, 1, dataNumRows, lastCol).getValues();

  const toWrite = new Array(dataNumRows);
  let wouldWrite = 0;
  let skippedExisting = 0;
  let placeholders = 0;

  for (let r = 0; r < dataNumRows; r++) {
    const row = block[r] || [];
    const existing = _cellStr_(row, outageIdCol);
    if (existing) {
      skippedExisting++;
      toWrite[r] = [existing];
      continue;
    }

    const systemRaw = _cellVal_(row, systemCol);
    const segmentRaw = _cellVal_(row, segmentCol);
    const failedDateRaw = failedDateCol ? _cellVal_(row, failedDateCol) : '';
    const failedTsRaw = failedTsCol ? _cellVal_(row, failedTsCol) : '';

    const failedForId = failedDateRaw || failedTsRaw;
    const outageId = _buildOutageIdFromFields_(systemRaw, segmentRaw, failedForId);

    toWrite[r] = [outageId];
    wouldWrite++;
    if (String(outageId).indexOf('00000000-') === 0 || String(outageId).indexOf('-UNKWN-') !== -1 || String(outageId).indexOf('-SUNKNOWN') !== -1) {
      placeholders++;
    }
  }

  if (wouldWrite === 0) {
    ui.alert('No blank OutageID cells found in the selected rows.\nSkipped (already set): ' + skippedExisting);
    return;
  }

  const resp = ui.alert(
    'Generate OutageID',
    'This will write OutageID for ' + wouldWrite + ' row(s) in the current selection.\n' +
      'It will NOT overwrite existing OutageID values.\n\n' +
      'Skipped (already set): ' + skippedExisting + '\n' +
      'Rows containing placeholder parts (e.g., 00000000 / UNKWN / SUNKNOWN): ' + placeholders + '\n\n' +
      'Proceed?',
    ui.ButtonSet.YES_NO
  );
  if (resp !== ui.Button.YES) {
    return;
  }

  // Write OutageID values back (single column) for the selected row block.
  sheet.getRange(dataStartRow, outageIdCol, dataNumRows, 1).setValues(toWrite);
  ui.alert('Done. Wrote OutageID for ' + wouldWrite + ' row(s).');
}

/**
 * Dev tool: Recompute OutageID in-sheet using the same normalization rules
 * as the backend `gmail-sheet-proxy/app.py::_build_outage_id_from_fields`.
 *
 * Safety:
 * - Operates ONLY on the current selection.
 * - Can OVERWRITE existing OutageID values, but requires explicit confirmation.
 */
function devRecomputeOutageIdForSelection() {
  const ui = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSheet();
  if (!sheet) {
    ui.alert('No active sheet.');
    return;
  }

  const excludeSet = _buildOutageIdExcludeSet_();
  if (excludeSet.has(sheet.getName())) {
    ui.alert('This sheet is excluded from Dev tools: ' + sheet.getName());
    return;
  }

  const range = sheet.getActiveRange();
  if (!range) {
    ui.alert('Select one or more data rows first.');
    return;
  }

  const startRow = range.getRow();
  const numRows = range.getNumRows();
  if (numRows < 1) {
    ui.alert('Select one or more data rows first.');
    return;
  }

  const resolved = _resolveOutageIdColumns_(sheet);
  if (!resolved || !resolved.outageIdCol) {
    ui.alert('Could not find/create an OutageID column on this sheet.');
    return;
  }

  const outageIdCol = resolved.outageIdCol;
  const systemCol = resolved.systemCol;
  const segmentCol = resolved.segmentCol;
  const failedDateCol = resolved.failedDateCol;
  const failedTsCol = resolved.failedTsCol;
  const lastCol = resolved.lastCol;

  if (!systemCol || !segmentCol) {
    ui.alert('Missing required columns on this sheet.\n\nRequired headers: System, Segment');
    return;
  }

  // Clamp selection to data rows only.
  const dataStartRow = Math.max(2, startRow);
  const dataEndRow = startRow + numRows - 1;
  if (dataEndRow < 2) {
    ui.alert('Select one or more data rows (row 2+).');
    return;
  }
  const dataNumRows = dataEndRow - dataStartRow + 1;

  const block = sheet.getRange(dataStartRow, 1, dataNumRows, lastCol).getValues();

  const toWrite = new Array(dataNumRows);
  let wouldFillBlank = 0;
  let wouldOverwrite = 0;
  let unchanged = 0;
  let placeholders = 0;
  let disambiguated = 0;

  const rowInfos = new Array(dataNumRows);
  const baseGroups = {};

  for (let r = 0; r < dataNumRows; r++) {
    const row = block[r] || [];
    const existing = _cellStr_(row, outageIdCol);

    const systemRaw = _cellVal_(row, systemCol);
    const segmentRaw = _cellVal_(row, segmentCol);
    const failedDateRaw = failedDateCol ? _cellVal_(row, failedDateCol) : '';
    const failedTsRaw = failedTsCol ? _cellVal_(row, failedTsCol) : '';
    const failedForId = failedDateRaw || failedTsRaw;

    const baseId = _buildOutageIdFromFields_(systemRaw, segmentRaw, failedForId);
    rowInfos[r] = { existing: existing, baseId: baseId, failedTsRaw: failedTsRaw, finalId: baseId };
    if (!baseGroups[baseId]) baseGroups[baseId] = [];
    baseGroups[baseId].push(r);

    // defer counts until after duplicate disambiguation
  }

  // Disambiguate any duplicate base OutageIDs within the selection.
  Object.keys(baseGroups).forEach(baseId => {
    const idxs = baseGroups[baseId] || [];
    if (idxs.length <= 1) return;

    const used = {};
    // Stable ordering by FailedTimeStamp (stringified) then row index.
    idxs.sort((i1, i2) => {
      const a = rowInfos[i1];
      const b = rowInfos[i2];
      const ta = String(a && a.failedTsRaw != null ? a.failedTsRaw : '');
      const tb = String(b && b.failedTsRaw != null ? b.failedTsRaw : '');
      if (ta < tb) return -1;
      if (ta > tb) return 1;
      return i1 - i2;
    });

    for (let k = 0; k < idxs.length; k++) {
      const idx = idxs[k];
      const info = rowInfos[idx];
      const hhmmss = _extractHhmmssUtc_(info.failedTsRaw);
      let candidate = baseId + '-T' + hhmmss;
      const seen = used[candidate] || 0;
      if (seen > 0) {
        candidate = candidate + '-N' + String(seen + 1);
      }
      used[baseId + '-T' + hhmmss] = seen + 1;
      info.finalId = candidate;
      disambiguated++;
    }
  });

  // Now populate toWrite and compute counts.
  for (let r = 0; r < dataNumRows; r++) {
    const info = rowInfos[r];
    const existing = info.existing;
    const computed = info.finalId;
    toWrite[r] = [computed];

    if (String(computed).indexOf('00000000-') === 0 || String(computed).indexOf('-UNKWN-') !== -1 || String(computed).indexOf('-SUNKNOWN') !== -1) {
      placeholders++;
    }

    if (!existing) {
      wouldFillBlank++;
      continue;
    }
    if (String(existing).trim() === String(computed).trim()) {
      unchanged++;
    } else {
      wouldOverwrite++;
    }
  }

  if (wouldFillBlank === 0 && wouldOverwrite === 0) {
    ui.alert('Recompute OutageID', 'All selected rows already match the computed OutageID.\nUnchanged: ' + unchanged, ui.ButtonSet.OK);
    return;
  }

  const resp = ui.alert(
    'Recompute OutageID (selection)',
    'This will recompute OutageID for ' + dataNumRows + ' selected row(s).\n\n' +
      'Will fill blanks: ' + wouldFillBlank + '\n' +
      'Will OVERWRITE existing OutageID: ' + wouldOverwrite + '\n' +
      'Will disambiguate duplicates (add -T...): ' + disambiguated + '\n' +
      'Unchanged: ' + unchanged + '\n\n' +
      'Rows containing placeholder parts (e.g., 00000000 / UNKWN / SUNKNOWN): ' + placeholders + '\n\n' +
      'Proceed?',
    ui.ButtonSet.YES_NO
  );
  if (resp !== ui.Button.YES) {
    return;
  }

  if (wouldOverwrite > 0) {
    const resp2 = ui.alert(
      'Confirm overwrite',
      'This will OVERWRITE OutageID in ' + wouldOverwrite + ' row(s).\n\nAre you absolutely sure?',
      ui.ButtonSet.YES_NO
    );
    if (resp2 !== ui.Button.YES) {
      return;
    }
  }

  sheet.getRange(dataStartRow, outageIdCol, dataNumRows, 1).setValues(toWrite);
  ui.alert('Done. Recomputed OutageID for ' + dataNumRows + ' row(s).');
}

/**
 * Dev tool: Generate OutageID for ALL eligible sheets.
 *
 * Safety:
 * - Skips excluded sheets.
 * - Skips header-only sheets.
 * - Writes only to blank OutageID cells (never overwrites).
 * - Prompts for confirmation with a summary before writing.
 */
function devGenerateOutageIdForAllSheets() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    ui.alert('No active spreadsheet.');
    return;
  }

  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(30 * 1000)) {
    ui.alert('Another operation is in progress. Please try again.');
    return;
  }

  try {
    const excludeSet = _buildOutageIdExcludeSet_();
    const sheets = ss.getSheets().filter(sh => sh && !excludeSet.has(sh.getName()));
    if (!sheets.length) {
      ui.alert('No eligible sheets found.');
      return;
    }

    // Phase 1: scan and compute plan (no writes).
    const plans = [];
    let totalWouldWrite = 0;
    let totalPlaceholders = 0;
    let scannedSheets = 0;
    let skippedSheets = 0;

    sheets.forEach(sheet => {
      try {
        const lastRow = sheet.getLastRow();
        const lastCol = Math.max(1, sheet.getLastColumn());
        if (lastRow < 2 || lastCol < 1) {
          skippedSheets++;
          return;
        }

        const resolved = _resolveOutageIdColumns_(sheet);
        if (!resolved || !resolved.outageIdCol || !resolved.systemCol || !resolved.segmentCol) {
          skippedSheets++;
          return;
        }

        scannedSheets++;

        const outageIdCol = resolved.outageIdCol;
        const systemCol = resolved.systemCol;
        const segmentCol = resolved.segmentCol;
        const failedDateCol = resolved.failedDateCol;
        const failedTsCol = resolved.failedTsCol;

        const dataNumRows = lastRow - 1;
        const block = sheet.getRange(2, 1, dataNumRows, resolved.lastCol).getValues();

        const toWrite = new Array(dataNumRows);
        let wouldWrite = 0;
        let placeholders = 0;

        for (let r = 0; r < dataNumRows; r++) {
          const row = block[r] || [];
          const existing = _cellStr_(row, outageIdCol);
          if (existing) {
            toWrite[r] = [existing];
            continue;
          }

          const systemRaw = _cellVal_(row, systemCol);
          const segmentRaw = _cellVal_(row, segmentCol);
          const failedDateRaw = failedDateCol ? _cellVal_(row, failedDateCol) : '';
          const failedTsRaw = failedTsCol ? _cellVal_(row, failedTsCol) : '';
          const failedForId = failedDateRaw || failedTsRaw;
          const outageId = _buildOutageIdFromFields_(systemRaw, segmentRaw, failedForId);

          toWrite[r] = [outageId];
          wouldWrite++;
          if (String(outageId).indexOf('00000000-') === 0 || String(outageId).indexOf('-UNKWN-') !== -1 || String(outageId).indexOf('-SUNKNOWN') !== -1) {
            placeholders++;
          }
        }

        if (wouldWrite > 0) {
          plans.push({
            sheet: sheet,
            startRow: 2,
            numRows: dataNumRows,
            outageIdCol: outageIdCol,
            values: toWrite,
            wouldWrite: wouldWrite,
            placeholders: placeholders,
          });
        }

        totalWouldWrite += wouldWrite;
        totalPlaceholders += placeholders;
      } catch (e) {
        skippedSheets++;
      }
    });

    if (totalWouldWrite === 0) {
      ui.alert(
        'No blank OutageID cells were found across eligible sheets.\n\n' +
          'Eligible sheets: ' + sheets.length + '\n' +
          'Scanned: ' + scannedSheets + '\n' +
          'Skipped (missing headers/protected/empty): ' + skippedSheets
      );
      return;
    }

    const resp = ui.alert(
      'Generate OutageID (all sheets)',
      'This will write OutageID for ' + totalWouldWrite + ' row(s) across ' + plans.length + ' sheet(s).\n' +
        'It will NOT overwrite existing OutageID values.\n\n' +
        'Rows containing placeholder parts (e.g., 00000000 / UNKWN / SUNKNOWN): ' + totalPlaceholders + '\n\n' +
        'Proceed?',
      ui.ButtonSet.YES_NO
    );
    if (resp !== ui.Button.YES) {
      return;
    }

    // Phase 2: perform writes.
    let wroteSheets = 0;
    plans.forEach(p => {
      try {
        p.sheet.getRange(p.startRow, p.outageIdCol, p.numRows, 1).setValues(p.values);
        wroteSheets++;
      } catch (e) {
        // ignore individual sheet write failures
      }
    });

    SpreadsheetApp.flush();
    ui.alert('Done. Wrote OutageID for ' + totalWouldWrite + ' row(s) across ' + wroteSheets + ' sheet(s).');
  } finally {
    try { lock.releaseLock(); } catch (e) { /* ignore */ }
  }
}

/**
 * Dev tool: Recompute OutageID for ALL eligible sheets.
 *
 * Safety:
 * - Skips excluded sheets.
 * - Skips header-only sheets.
 * - CAN OVERWRITE existing OutageID values; requires explicit confirmation.
 * - Prompts for confirmation with a summary before writing.
 */
function devRecomputeOutageIdForAllSheets() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    ui.alert('No active spreadsheet.');
    return;
  }

  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(30 * 1000)) {
    ui.alert('Another operation is in progress. Please try again.');
    return;
  }

  try {
    const excludeSet = _buildOutageIdExcludeSet_();
    const sheets = ss.getSheets().filter(sh => sh && !excludeSet.has(sh.getName()));
    if (!sheets.length) {
      ui.alert('No eligible sheets found.');
      return;
    }

    // Phase 1: scan and compute plan (no writes).
    const plans = [];
    let totalRows = 0;
    let totalWouldFillBlank = 0;
    let totalWouldOverwrite = 0;
    let totalUnchanged = 0;
    let totalPlaceholders = 0;
    let totalDisambiguated = 0;
    let totalDuplicateGroups = 0;
    let scannedSheets = 0;
    let skippedSheets = 0;

    const sheetPlans = [];
    const allRows = [];
    const baseGroups = {};

    sheets.forEach(sheet => {
      try {
        const lastRow = sheet.getLastRow();
        const lastCol = Math.max(1, sheet.getLastColumn());
        if (lastRow < 2 || lastCol < 1) {
          skippedSheets++;
          return;
        }

        const resolved = _resolveOutageIdColumns_(sheet);
        if (!resolved || !resolved.outageIdCol || !resolved.systemCol || !resolved.segmentCol) {
          skippedSheets++;
          return;
        }

        scannedSheets++;

        const outageIdCol = resolved.outageIdCol;
        const systemCol = resolved.systemCol;
        const segmentCol = resolved.segmentCol;
        const failedDateCol = resolved.failedDateCol;
        const failedTsCol = resolved.failedTsCol;

        const dataNumRows = lastRow - 1;
        totalRows += dataNumRows;

        const block = sheet.getRange(2, 1, dataNumRows, resolved.lastCol).getValues();
        const rowInfos = new Array(dataNumRows);

        for (let r = 0; r < dataNumRows; r++) {
          const row = block[r] || [];
          const existing = _cellStr_(row, outageIdCol);

          const systemRaw = _cellVal_(row, systemCol);
          const segmentRaw = _cellVal_(row, segmentCol);
          const failedDateRaw = failedDateCol ? _cellVal_(row, failedDateCol) : '';
          const failedTsRaw = failedTsCol ? _cellVal_(row, failedTsCol) : '';
          const failedForId = failedDateRaw || failedTsRaw;

          const baseId = _buildOutageIdFromFields_(systemRaw, segmentRaw, failedForId);
          rowInfos[r] = { existing: existing, baseId: baseId, failedTsRaw: failedTsRaw, finalId: baseId };

          const item = { sheetName: sheet.getName(), planIdx: sheetPlans.length, rowIdx: r, baseId: baseId, failedTsRaw: failedTsRaw };
          allRows.push(item);
          if (!baseGroups[baseId]) baseGroups[baseId] = [];
          baseGroups[baseId].push(item);
        }

        sheetPlans.push({
          sheet: sheet,
          startRow: 2,
          numRows: dataNumRows,
          outageIdCol: outageIdCol,
          lastCol: resolved.lastCol,
          rowInfos: rowInfos,
        });
      } catch (e) {
        skippedSheets++;
      }
    });

    // Disambiguate duplicates across ALL eligible sheets (not just within a sheet).
    Object.keys(baseGroups).forEach(baseId => {
      const items = baseGroups[baseId] || [];
      if (items.length <= 1) return;

      totalDuplicateGroups++;
      // Stable ordering by timestamp string then sheet name then row.
      items.sort((a, b) => {
        const ta = String(a && a.failedTsRaw != null ? a.failedTsRaw : '');
        const tb = String(b && b.failedTsRaw != null ? b.failedTsRaw : '');
        if (ta < tb) return -1;
        if (ta > tb) return 1;
        const sa = String(a.sheetName || '');
        const sb = String(b.sheetName || '');
        if (sa < sb) return -1;
        if (sa > sb) return 1;
        return (a.rowIdx || 0) - (b.rowIdx || 0);
      });

      const used = {};
      for (let k = 0; k < items.length; k++) {
        const it = items[k];
        const sp = sheetPlans[it.planIdx];
        const info = sp && sp.rowInfos ? sp.rowInfos[it.rowIdx] : null;
        if (!info) continue;

        const hhmmss = _extractHhmmssUtc_(info.failedTsRaw);
        let candidate = baseId + '-T' + hhmmss;
        const seen = used[candidate] || 0;
        if (seen > 0) {
          candidate = candidate + '-N' + String(seen + 1);
        }
        used[baseId + '-T' + hhmmss] = seen + 1;
        info.finalId = candidate;
        totalDisambiguated++;
      }
    });

    // Build write plans + totals AFTER disambiguation.
    sheetPlans.forEach(sp => {
      try {
        const toWrite = new Array(sp.numRows);
        let wouldFillBlank = 0;
        let wouldOverwrite = 0;
        let unchanged = 0;
        let placeholders = 0;

        for (let r = 0; r < sp.numRows; r++) {
          const info = sp.rowInfos[r];
          const existing = info.existing;
          const computed = info.finalId;
          toWrite[r] = [computed];

          if (String(computed).indexOf('00000000-') === 0 || String(computed).indexOf('-UNKWN-') !== -1 || String(computed).indexOf('-SUNKNOWN') !== -1) {
            placeholders++;
          }

          if (!existing) {
            wouldFillBlank++;
          } else if (String(existing).trim() === String(computed).trim()) {
            unchanged++;
          } else {
            wouldOverwrite++;
          }
        }

        if (wouldFillBlank > 0 || wouldOverwrite > 0) {
          plans.push({
            sheet: sp.sheet,
            startRow: sp.startRow,
            numRows: sp.numRows,
            outageIdCol: sp.outageIdCol,
            values: toWrite,
            wouldFillBlank: wouldFillBlank,
            wouldOverwrite: wouldOverwrite,
            unchanged: unchanged,
            placeholders: placeholders,
          });
        }

        totalWouldFillBlank += wouldFillBlank;
        totalWouldOverwrite += wouldOverwrite;
        totalUnchanged += unchanged;
        totalPlaceholders += placeholders;
      } catch (e) {
        // ignore
      }
    });

    if (plans.length === 0) {
      ui.alert(
        'Recompute OutageID (all sheets)',
        'No changes needed across eligible sheets.\n\n' +
          'Eligible sheets: ' + sheets.length + '\n' +
          'Scanned: ' + scannedSheets + '\n' +
          'Skipped (missing headers/protected/empty): ' + skippedSheets,
        ui.ButtonSet.OK
      );
      return;
    }

    const resp = ui.alert(
      'Recompute OutageID (all sheets)',
      'This will recompute OutageID across eligible sheets.\n\n' +
        'Total data rows scanned: ' + totalRows + '\n' +
        'Will fill blanks: ' + totalWouldFillBlank + '\n' +
        'Will OVERWRITE existing OutageID: ' + totalWouldOverwrite + '\n' +
        'Will disambiguate duplicates (add -T...): ' + totalDisambiguated + ' (groups: ' + totalDuplicateGroups + ')\n' +
        'Unchanged: ' + totalUnchanged + '\n\n' +
        'Rows containing placeholder parts (e.g., 00000000 / UNKWN / SUNKNOWN): ' + totalPlaceholders + '\n\n' +
        'Proceed?',
      ui.ButtonSet.YES_NO
    );
    if (resp !== ui.Button.YES) {
      return;
    }

    if (totalWouldOverwrite > 0) {
      const resp2 = ui.alert(
        'Confirm overwrite',
        'This will OVERWRITE OutageID in ' + totalWouldOverwrite + ' row(s) across eligible sheets.\n\nAre you absolutely sure?',
        ui.ButtonSet.YES_NO
      );
      if (resp2 !== ui.Button.YES) {
        return;
      }
    }

    // Phase 2: perform writes.
    let wroteSheets = 0;
    let changedSheets = 0;
    plans.forEach(p => {
      try {
        p.sheet.getRange(p.startRow, p.outageIdCol, p.numRows, 1).setValues(p.values);
        wroteSheets++;
        changedSheets++;
      } catch (e) {
        // ignore individual sheet write failures
      }
    });

    SpreadsheetApp.flush();
    ui.alert(
      'Done. Recomputed OutageID across ' + changedSheets + ' sheet(s).\n' +
        'Filled blanks: ' + totalWouldFillBlank + '\n' +
        'Overwrote existing: ' + totalWouldOverwrite + '\n' +
        'Disambiguated duplicates (added -T...): ' + totalDisambiguated
    );
  } finally {
    try { lock.releaseLock(); } catch (e) { /* ignore */ }
  }
}

function _extractHhmmssUtc_(value) {
  try {
    if (value instanceof Date && !isNaN(value.getTime())) {
      return Utilities.formatDate(value, 'UTC', 'HHmmss');
    }
  } catch (e) {
    // ignore
  }

  const s = (value == null) ? '' : String(value).trim();
  if (!s) return '000000';

  // Try parseable timestamp strings first.
  try {
    const d = new Date(s);
    if (d instanceof Date && !isNaN(d.getTime())) {
      return Utilities.formatDate(d, 'UTC', 'HHmmss');
    }
  } catch (e) {
    // ignore
  }

  // Regex fallback: HH:MM(:SS)
  const m = s.match(/\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b/);
  if (m) {
    const hh = (m[1].length === 1 ? '0' : '') + m[1];
    const mm = m[2];
    const ss = m[3] ? m[3] : '00';
    return hh + mm + ss;
  }

  return '000000';
}

function _buildOutageIdExcludeSet_() {
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

  return new Set(exclude.map(x => String(x || '').trim()).filter(Boolean));
}

function _resolveOutageIdColumns_(sheet) {
  if (!sheet) return null;

  // First, try to ensure the trailing audit block exists (preferred OutageID column).
  let ensured = null;
  try {
    if (typeof _ensureReviewAuditHeaders_ === 'function') {
      ensured = _ensureReviewAuditHeaders_(sheet);
    }
  } catch (e) {
    ensured = null;
  }

  const lastCol = Math.max(1, sheet.getLastColumn());
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0] || [];

  function normHeader(v) {
    if (typeof _normalizeHeaderKey_ === 'function') return _normalizeHeaderKey_(v);
    return String(v || '').trim().toLowerCase().replace(/\s+/g, '').replace(/_/g, '');
  }

  function findCol(keys) {
    const wanted = new Set((keys || []).map(k => String(k || '').trim().toLowerCase()).filter(Boolean));
    for (let i = 0; i < headers.length; i++) {
      const k = normHeader(headers[i]);
      if (wanted.has(k)) return i + 1;
    }
    return null;
  }

  const auditCols = ensured && ensured.auditCols ? ensured.auditCols : null;
  const preferredOutageIdCol = auditCols && auditCols.OutageID ? auditCols.OutageID : null;
  const outageIdCol = preferredOutageIdCol || findCol(['outageid']);

  return {
    lastCol: lastCol,
    outageIdCol: outageIdCol,
    systemCol: findCol(['system']),
    segmentCol: findCol(['segment']),
    failedDateCol: findCol(['faileddate']),
    failedTsCol: findCol(['failedtimestamp']),
  };
}

function _cellVal_(row, col1Based) {
  const idx = (col1Based || 1) - 1;
  return idx >= 0 && idx < (row || []).length ? row[idx] : '';
}

function _cellStr_(row, col1Based) {
  const v = _cellVal_(row, col1Based);
  const s = (v == null) ? '' : String(v).trim();
  return s;
}

function _buildOutageIdFromFields_(system, segment, failedDate) {
  const systemPart = _normalizeOutageSystemPart_(system);
  const segmentPart = _normalizeOutageSegmentPart_(segment);
  const datePart = _normalizeOutageDatePart_(failedDate);
  return datePart + '-' + systemPart + '-' + segmentPart;
}

function _normalizeOutageSystemPart_(system, length) {
  const maxLen = (typeof length === 'number' && isFinite(length)) ? length : 5;
  let s = (system == null) ? '' : String(system).trim();
  s = s.replace(/[^A-Za-z0-9]+/g, '').toUpperCase();
  if (!s) return 'UNKWN';
  return maxLen > 0 ? s.substring(0, maxLen) : s;
}

function _normalizeOutageSegmentPart_(segment) {
  let s = (segment == null) ? '' : String(segment).trim();
  if (!s || s.toLowerCase() === 'unknown') return 'SUNKNOWN';

  s = s.replace(/segments?/gi, 'S');
  s = s.replace(/[^A-Za-z0-9]+/g, '').toUpperCase();
  if (!s) return 'SUNKNOWN';

  if (s[0] !== 'S') s = 'S' + s;
  s = s.replace(/^S+/, 'S');
  if (s === 'S') return 'SUNKNOWN';

  const tail = s.substring(1).toUpperCase();
  if (
    tail.indexOf('UNKNOWN') !== -1 ||
    tail.indexOf('UNKWN') !== -1 ||
    tail.indexOf('UNKNO') !== -1 ||
    (tail.startsWith('UN') && tail.endsWith('KNOW')) ||
    ['UNK', 'UNKN', 'UNKNW', 'UNKNWN'].indexOf(tail) !== -1
  ) {
    return 'SUNKNOWN';
  }
  return s;
}

function _extractDatePartFromText_(text) {
  if (text == null) return null;
  const t = String(text);

  // Sheets often stores dates as typed Date values (handled elsewhere), but when the
  // cell contains text like "01/04/2026" the day/month order depends on spreadsheet locale.
  // Default to day-first for most locales, but treat US locales as month-first.
  let monthFirst = false;
  try {
    const locale = String(SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetLocale() || '');
    // e.g. "en_US" => month-first
    monthFirst = /(^|[_-])US$/i.test(locale);
  } catch (e) {
    monthFirst = false;
  }

  // Prefer explicit D/M/Y parsing when present.
  // Domain reality: these outage sheets commonly use DD/MM/YYYY.
  // We therefore *prefer day-first*, but fall back to month-first only when
  // day-first would be invalid (e.g., 24/01/2026 cannot be MM/DD).
  // If both interpretations are valid (ambiguous like 01/04/2026), default to
  // day-first to match backend normalization.
  const dmy = t.match(/\b(\d{1,2})[\/-](\d{1,2})[\/-](\d{2}|\d{4})\b/);
  if (dmy) {
    const a = parseInt(dmy[1], 10);
    const b = parseInt(dmy[2], 10);
    let y = parseInt(dmy[3], 10);
    if (!isNaN(y) && y < 100) y = (y < 70 ? 2000 + y : 1900 + y);

    function _validYMD_(yy, mm, dd) {
      return (
        !isNaN(yy) && yy >= 1900 && yy <= 2100 &&
        !isNaN(mm) && mm >= 1 && mm <= 12 &&
        !isNaN(dd) && dd >= 1 && dd <= 31
      );
    }

    const d1 = a; // DD/MM
    const m1 = b;
    const d2 = b; // MM/DD
    const m2 = a;

    const ok1 = _validYMD_(y, m1, d1);
    const ok2 = _validYMD_(y, m2, d2);

    let d = null;
    let m = null;

    if (ok1 && !ok2) {
      d = d1;
      m = m1;
    } else if (!ok1 && ok2) {
      d = d2;
      m = m2;
    } else if (ok1 && ok2) {
      // Ambiguous: 01/04/2026 could be 1 Apr or 4 Jan.
      // Default to day-first.
      d = d1;
      m = m1;
    } else {
      d = null;
      m = null;
    }

    if (d != null && m != null) {
      const mm = (m < 10 ? '0' : '') + String(m);
      const dd = (d < 10 ? '0' : '') + String(d);
      return String(y) + mm + dd;
    }
  }

  const digits = t.replace(/\D/g, '');

  if (digits.length === 8) {
    // If YYYYMMDD, keep as-is.
    const y1 = parseInt(digits.substring(0, 4), 10);
    if (!isNaN(y1) && y1 >= 1900 && y1 <= 2100) return digits;
    // If DDMMYYYY, reorder.
    const y2 = parseInt(digits.substring(4, 8), 10);
    if (!isNaN(y2) && y2 >= 1900 && y2 <= 2100) {
      return digits.substring(4, 8) + digits.substring(2, 4) + digits.substring(0, 2);
    }
    return digits;
  }

  if (digits.length === 6) {
    // Handle DDMMYY and YYMMDD (with 2-digit year pivot).
    const a = parseInt(digits.substring(0, 2), 10);
    const b = parseInt(digits.substring(2, 4), 10);
    const c = parseInt(digits.substring(4, 6), 10);
    const pivotYear = yy => (yy < 70 ? 2000 + yy : 1900 + yy);

    // DDMMYY
    if (!isNaN(a) && !isNaN(b) && a >= 1 && a <= 31 && b >= 1 && b <= 12) {
      const y = pivotYear(c);
      return String(y) + (b < 10 ? '0' : '') + String(b) + (a < 10 ? '0' : '') + String(a);
    }
    // YYMMDD
    if (!isNaN(b) && !isNaN(c) && b >= 1 && b <= 12 && c >= 1 && c <= 31) {
      const y = pivotYear(a);
      return String(y) + (b < 10 ? '0' : '') + String(b) + (c < 10 ? '0' : '') + String(c);
    }

    // Special case like "19/2026" -> digits=192026 (DDYYYY). Prefer year-only placeholder.
    const yMaybe = parseInt(digits.substring(2, 6), 10);
    if (!isNaN(yMaybe) && yMaybe >= 1900 && yMaybe <= 2100) return String(yMaybe) + '0000';

    return digits + '00';
  }

  if (digits.length === 4) {
    const y = parseInt(digits, 10);
    if (!isNaN(y) && y >= 1900 && y <= 2100) return digits + '0000';
    return digits + '0000';
  }

  const m8 = t.match(/\d{8}/g);
  if (m8 && m8.length) return m8[m8.length - 1];
  const m6 = t.match(/\d{6}/g);
  if (m6 && m6.length) return m6[m6.length - 1] + '00';
  const m4 = t.match(/\d{4}/g);
  if (m4 && m4.length) return m4[m4.length - 1] + '0000';
  return null;
}

function _normalizeOutageDatePart_(failedDate) {
  if (failedDate instanceof Date && !isNaN(failedDate.getTime())) {
    // Sheets time-only values often serialize to year 1899; treat as blank (matches backend behavior).
    if (failedDate.getFullYear && failedDate.getFullYear() === 1899) {
      return '00000000';
    }
    // Use the spreadsheet timezone (not the Apps Script project timezone) to avoid
    // off-by-one-day shifts when formatting typed Sheets dates.
    let tz = Session.getScriptTimeZone();
    try {
      tz = SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone() || tz;
    } catch (e) {
      // ignore
    }
    return Utilities.formatDate(failedDate, tz, 'yyyyMMdd');
  }

  // Support YYYY-MM-DD and partial placeholders like YYYY-00-00.
  if (typeof failedDate === 'string') {
    const m = failedDate.match(/^\s*(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?\s*$/);
    if (m) {
      const yearS = m[1];
      const monthS = m[2];
      const dayS = m[3];
      let month = null;
      let day = null;
      try { month = (monthS != null) ? parseInt(monthS, 10) : null; } catch (e) { month = null; }
      try { day = (dayS != null) ? parseInt(dayS, 10) : null; } catch (e) { day = null; }

      if (month == null || !(month >= 0 && month <= 12)) {
        return yearS + '0000';
      }
      const monthOut = (month < 10 ? '0' : '') + String(month);
      let dayOut;
      if (day == null || !(day >= 0 && day <= 31)) {
        dayOut = '00';
      } else {
        dayOut = (day < 10 ? '0' : '') + String(day);
      }
      return yearS + monthOut + dayOut;
    }
  }

  const fromText = _extractDatePartFromText_(failedDate);
  if (fromText) return fromText;
  return '00000000';
}
