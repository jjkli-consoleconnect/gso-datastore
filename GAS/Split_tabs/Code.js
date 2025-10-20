function consolidateAllSimple() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const targetName = 'BigQuery-consolidated';
  let target = ss.getSheetByName(targetName);
  if (!target) target = ss.insertSheet(targetName);

  const exclude = ['BigQuery-consolidated','ConsolidationSummary','ConsolidationErrors','HeaderDump','HeaderCheck','SourceSpreadsheet'];
  const sheets = ss.getSheets();

  let headerRow = null;
  const rows = [];
  let maxCols = 1;

  for (let i = 0; i < sheets.length; i++) {
    const sh = sheets[i];
    const name = sh.getName();
    if (exclude.indexOf(name) !== -1) continue;
    const lastCol = sh.getLastColumn();
    const lastRow = sh.getLastRow();
    if (lastCol === 0 || lastRow <= 1) continue;
    const srcHeader = sh.getRange(1, 1, 1, lastCol).getValues()[0];
    if (!headerRow) {
      headerRow = srcHeader.slice();
      headerRow[0] = 'System';
    }
    const data = sh.getRange(2, 1, lastRow - 1, lastCol).getValues();
    for (let r = 0; r < data.length; r++) {
      const srcRow = data[r];
      const nonEmpty = srcRow.some(c => c !== null && c !== '');
      if (!nonEmpty) continue;
      const copy = srcRow.slice();
      copy[0] = name;
      rows.push(copy);
      if (copy.length > maxCols) maxCols = copy.length;
    }
  }

  if (!headerRow) headerRow = new Array(maxCols).fill('');
  while (headerRow.length < maxCols) headerRow.push('');
  if (headerRow.length > maxCols) headerRow.length = maxCols;

  const normalize = r => {
    const out = r.slice();
    while (out.length < maxCols) out.push('');
    if (out.length > maxCols) out.length = maxCols;
    return out;
  };

  const finalRows = rows.map(normalize);
  const DATA_COLS = 14; // A..N
  const FORMULA_START_COL = 15; // O
  const FORMULA_END_COL = 19;   // S
  const FORMULA_COLS = FORMULA_END_COL - FORMULA_START_COL + 1;
  const dataRowCount = finalRows.length;

  // Snapshot formulas from O2:S2
  let snapshotFormulas = null;
  try {
    if (target.getLastColumn() >= FORMULA_START_COL) {
      snapshotFormulas = target.getRange(2, FORMULA_START_COL, 1, FORMULA_COLS).getFormulasR1C1();
    } else {
      snapshotFormulas = [new Array(FORMULA_COLS).fill('')];
    }
  } catch (e) { snapshotFormulas = null; }

  // Clear A..N and write header + data into A..N only
  try {
    const maxRows = target.getMaxRows();
    if (maxRows > 1) target.getRange(2, 1, Math.max(1, maxRows - 1), DATA_COLS).clearContent();
  } catch (e) { /* ignore */ }

  try {
    // Preserve manual header edits: only write header if A1 is empty.
    const preserveManualHeader = true;
    let shouldWriteHeader = true;
    try {
      const existingA1 = target.getRange(1, 1).getValue();
      if (preserveManualHeader && existingA1 !== '' && existingA1 !== null && existingA1 !== undefined) {
        shouldWriteHeader = false;
      }
    } catch (e) {
      // If we can't read A1 for some reason, fall back to writing header
      shouldWriteHeader = true;
    }
    if (shouldWriteHeader) {
      target.getRange(1, 1, 1, Math.min(headerRow.length, DATA_COLS)).setValues([headerRow.slice(0, DATA_COLS)]);
    }
  } catch (e) { /* ignore */ }

  if (finalRows.length > 0) {
    try {
      const rowsToWrite = finalRows.map(r => {
        const out = r.slice();
        while (out.length < DATA_COLS) out.push('');
        if (out.length > DATA_COLS) out.length = DATA_COLS;
        return out;
      });
      target.getRange(2, 1, rowsToWrite.length, DATA_COLS).setValues(rowsToWrite);
    } catch (e) { /* ignore */ }
  }

  // Restore O2:S2 formulas and copy down
  try {
    if (snapshotFormulas) {
      try { target.getRange(2, FORMULA_START_COL, 1, snapshotFormulas[0].length).setFormulasR1C1(snapshotFormulas); } catch (e) { /* ignore */ }
    }
    fillFormulasInConsolidated(2, FORMULA_START_COL, FORMULA_END_COL, dataRowCount);
  } catch (e) { /* ignore */ }

  const log = ss.getSheetByName('ConsolidationSummary') || ss.insertSheet('ConsolidationSummary');
  log.appendRow([new Date(), 'consolidateAllSimple', 'sheets', sheets.length, 'rowsWritten', finalRows.length]);
}

function fillFormulasInConsolidated(srcRow, startCol, endCol, dataRowCount) {
  srcRow = srcRow || 2; startCol = startCol || 15; endCol = endCol || 19;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const target = ss.getSheetByName('BigQuery-consolidated');
  if (!target) return;
  const numCols = endCol - startCol + 1;
  dataRowCount = dataRowCount || 0;

  const rowsNeedingFormulas = Math.max(0, dataRowCount - 1);
  try {
    if (rowsNeedingFormulas > 0) {
      const srcRange = target.getRange(srcRow, startCol, 1, numCols);
      const destRange = target.getRange(srcRow + 1, startCol, rowsNeedingFormulas, numCols);
      srcRange.copyTo(destRange, SpreadsheetApp.CopyPasteType.PASTE_FORMULA, false);
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

function onOpen(e) {
  try {
    const ui = SpreadsheetApp.getUi();
    ui.createMenu('BQ Sync').addItem('Sync to BQ-consolidated', 'consolidateAllSimple').addToUi();
  } catch (e) { /* ignore */ }
}
