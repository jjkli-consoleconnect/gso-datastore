/**
 * Minimal consolidation: keep only full rebuild + formula helper + onOpen menu.
 */

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

  // Snapshot formulas from O2:S2
  let snapshotFormulas = null;
  try {
    const startCol = 15; const endCol = 19; const numCols = endCol - startCol + 1;
    if (target.getLastColumn() >= startCol) snapshotFormulas = target.getRange(2, startCol, 1, numCols).getFormulasR1C1();
    else snapshotFormulas = [new Array(numCols).fill('')];
  } catch (e) { snapshotFormulas = null; }

  // Clear A..N and write header + data into A..N only
  try {
    const maxRows = target.getMaxRows();
    if (maxRows > 1) target.getRange(2, 1, Math.max(1, maxRows - 1), DATA_COLS).clearContent();
  } catch (e) { /* ignore */ }

  try { target.getRange(1, 1, 1, Math.min(headerRow.length, DATA_COLS)).setValues([headerRow.slice(0, DATA_COLS)]); } catch (e) { /* ignore */ }

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
      try { target.getRange(2, 15, 1, snapshotFormulas[0].length).setFormulasR1C1(snapshotFormulas); } catch (e) { /* ignore */ }
    }
    fillFormulasInConsolidated(2, 15, 19);
  } catch (e) { /* ignore */ }

  const log = ss.getSheetByName('ConsolidationSummary') || ss.insertSheet('ConsolidationSummary');
  log.appendRow([new Date(), 'consolidateAllSimple', 'sheets', sheets.length, 'rowsWritten', finalRows.length]);
}

function fillFormulasInConsolidated(srcRow, startCol, endCol) {
  srcRow = srcRow || 2; startCol = startCol || 15; endCol = endCol || 19;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const target = ss.getSheetByName('BigQuery-consolidated');
  if (!target) return;
  const lastRow = target.getLastRow();
  if (lastRow <= srcRow) return;
  const numCols = endCol - startCol + 1;
  try {
    const srcRange = target.getRange(srcRow, startCol, 1, numCols);
    const destRange = target.getRange(2, startCol, lastRow - 1, numCols);
    srcRange.copyTo(destRange, SpreadsheetApp.CopyPasteType.PASTE_FORMULA, false);
  } catch (e) { /* ignore */ }
}

function onOpen(e) {
  try {
    const ui = SpreadsheetApp.getUi();
    ui.createMenu('BQ Sync').addItem('Sync to BQ-consolidated', 'consolidateAllSimple').addToUi();
  } catch (e) { /* ignore */ }
}
