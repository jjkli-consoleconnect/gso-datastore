/**
 * Audit logging for reviewer edits.
 * Logs per-cell changes to BigQuery via Cloud Run.
 */

function auditOnEdit(e) {
	if (!CONFIG || !CONFIG.AUDIT || !CONFIG.AUDIT.ENABLED) return;
	if (!e || !e.range) return;

	const sheet = e.range.getSheet();
	const sheetName = sheet.getName();
	if (sheetName === CONFIG.AUDIT.SHADOW_SHEET_NAME) return;
	if (_shouldSkipAuditSheet_(sheetName)) return;

	const lock = LockService.getDocumentLock();
	if (!lock.tryLock(5000)) return;

	try {
		const ss = e.source;
		// Get/create global shadow snapshot. This shadow is append-only so it can
		// represent AI baseline values across multiple system sheets.
		let shadow = ss.getSheetByName(CONFIG.AUDIT.SHADOW_SHEET_NAME);
		if (!shadow) {
			Logger.log('Audit shadow sheet not found; creating it now (global snapshot)');
			shadow = getOrCreateShadowSheetFromAllSheets_(ss);
		}
		if (!shadow) {
			Logger.log('Audit shadow sheet unavailable, skipping audit');
			return;
		}

		// Ensure the shadow contains any new EmailIDs from this edited sheet.
		try {
			ensureShadowIncludesSheetRows_(shadow, sheet);
		} catch (ignore) {}

		const range = e.range;
		const startRow = range.getRow();
		const startCol = range.getColumn();
		const numRows = range.getNumRows();
		const numCols = range.getNumColumns();

		const newValues = range.getValues();

		const sheetHeaders = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
		const sheetEmailIdCol = getEmailIdColumnIndex_(sheetHeaders);
		if (sheetEmailIdCol <= 0) return;

		const shadowHeaders = shadow.getLastRow() >= 1
			? shadow.getRange(1, 1, 1, shadow.getLastColumn()).getValues()[0]
			: [];
		const shadowEmailIdCol = getEmailIdColumnIndex_(shadowHeaders);
		if (shadowEmailIdCol <= 0) return;

		const timestamp = new Date().toISOString();
		const editor = getEditorEmail_();

		// Load schema to check field nullability
		const fieldModes = getFieldModesFromSchema_();

		const records = [];

		for (let r = 0; r < numRows; r++) {
			const rowIndex = startRow + r;
			if (rowIndex === 1) continue; // skip header row

			const emailId = sheetEmailIdCol > 0 ? String(sheet.getRange(rowIndex, sheetEmailIdCol).getValue() || '').trim() : '';

			if (!emailId) continue;
			const shadowResolved = resolveShadowRow_(shadow, shadowEmailIdCol, emailId, rowIndex);
			if (!shadowResolved.matched) continue;
			const shadowRowIndex = shadowResolved.rowIndex;
			const shadowRow = shadow.getRange(shadowRowIndex, 1, 1, shadow.getLastColumn()).getValues()[0];

			const modifications = [];

			for (let c = 0; c < numCols; c++) {
				const colIndex = startCol + c;
				const columnName = sheetHeaders[colIndex - 1] || `Column${colIndex}`;
				const shadowColIndex = (shadowHeaders && shadowHeaders.length)
					? (shadowHeaders.indexOf(columnName) + 1)
					: colIndex;
				if (shadowColIndex <= 0 || shadowColIndex > shadowRow.length) continue;

				const oldValue = shadowRow[shadowColIndex - 1];
				const newValue = newValues[r][c];

				const oldValueStr = oldValue == null ? '' : String(oldValue);
				const newValueStr = newValue == null ? '' : String(newValue);

				if (oldValueStr === newValueStr) continue;

				// columnName is derived from the edited sheet headers.
				
				// Track blank->non-blank edits (including REQUIRED fields)
				// Shadow is the AI baseline; edits are human corrections
				if (oldValueStr === '' && newValueStr !== '') {
					const fieldMode = fieldModes[columnName];
					if (fieldMode === 'REQUIRED') {
						// keep blank->non-blank audit for required fields
					}
					// For NULLABLE fields, track the blank→non-blank change
				}

				modifications.push({
					columnName,
					oldValue: oldValueStr,
					newValue: newValueStr
				});
			}

			if (modifications.length > 0) {
				records.push({
					timestamp,
					editor,
					emailId,
					modifications
				});
			}
		}

		// Buffer audit records WITHOUT updating shadow
		// Shadow permanently holds original AI-generated values for ML training
		// Training data = what AI thought (shadow) vs what human corrected (current)
		if (records.length) {
			bufferAuditRecords_(records);
			// Intentionally do NOT flush here.
			// Audit is flushed by the consolidate workflow (end of consolidateAllSimple)
			// to avoid calling Cloud Run on every edit.
		}
	} catch (err) {
		Logger.log('Audit onEdit error: ' + err);
	} finally {
		lock.releaseLock();
	}
}

function _shouldSkipAuditSheet_(sheetName) {
	const name = String(sheetName || '').trim();
	if (!name) return true;
	if (CONFIG && CONFIG.SHEETS && name === CONFIG.SHEETS.EMAIL_DETAILS) return true;
	if (CONFIG && CONFIG.AUDIT && name === CONFIG.AUDIT.SHADOW_SHEET_NAME) return true;
	const skip = new Set([
		'BigQuery-consolidated',
		'ConsolidationSummary',
		'ConsolidationErrors',
		'HeaderDump',
		'HeaderCheck',
		'SourceSpreadsheet'
	]);
	return skip.has(name);
}

function _hasAuditTriggerInstalled_() {
	try {
		const triggers = ScriptApp.getProjectTriggers();
		return triggers.some(t => t.getHandlerFunction() === 'auditOnEdit' && t.getEventType() === ScriptApp.EventType.ON_EDIT);
	} catch (e) {
		return false;
	}
}

function checkAuditSetup() {
	const ss = SpreadsheetApp.getActiveSpreadsheet();
	const shadow = ss.getSheetByName(CONFIG.AUDIT.SHADOW_SHEET_NAME);
	const triggerInstalled = _hasAuditTriggerInstalled_();
	const enabled = !!(CONFIG && CONFIG.AUDIT && CONFIG.AUDIT.ENABLED);
	const props = PropertiesService.getDocumentProperties();
	const existing = props.getProperty('AUDIT_BUFFER');
	let bufferCount = 0;
	if (existing) {
		try { bufferCount = (JSON.parse(existing) || []).length; } catch (e) { bufferCount = -1; }
	}

	const msg =
		'Audit enabled: ' + enabled + '\n' +
		'Audit trigger installed: ' + triggerInstalled + '\n' +
		'Shadow sheet exists (_AuditShadow): ' + (!!shadow) + '\n' +
		'Audit buffer count: ' + bufferCount + '\n\n' +
		'Next steps:\n' +
		'- If audit enabled is false: set CONFIG.AUDIT.ENABLED = true\n' +
		'- If trigger is false: run Setup → Install Audit\n' +
		'- If shadow missing: run Setup → Install Audit and make one edit in a system sheet';

	SpreadsheetApp.getUi().alert('Audit Setup', msg, SpreadsheetApp.getUi().ButtonSet.OK);
}

function installAuditTrigger() {
	const triggers = ScriptApp.getProjectTriggers();
	const exists = triggers.some(t => t.getHandlerFunction() === 'auditOnEdit' && t.getEventType() === ScriptApp.EventType.ON_EDIT);
	if (!exists) {
		ScriptApp.newTrigger('auditOnEdit')
			.forSpreadsheet(SpreadsheetApp.getActiveSpreadsheet())
			.onEdit()
			.create();
	}

	// Ensure audit shadow exists so audit can buffer immediately.
	try {
		const ss = SpreadsheetApp.getActiveSpreadsheet();
		getOrCreateShadowSheetFromAllSheets_(ss);
	} catch (e) {
		Logger.log('installAuditTrigger: Failed to create shadow sheet: ' + e);
	}
	if (CONFIG && CONFIG.AUDIT && !CONFIG.AUDIT.ENABLED) {
		SheetUtils.showAlert('Audit trigger installed. Note: CONFIG.AUDIT.ENABLED is false, so edits will not be logged until enabled.');
		return;
	}
	SheetUtils.showAlert('Audit trigger installed.');
}

function removeAuditTrigger() {
	const triggers = ScriptApp.getProjectTriggers();
	triggers.forEach(t => {
		if (t.getHandlerFunction() === 'auditOnEdit' && t.getEventType() === ScriptApp.EventType.ON_EDIT) {
			ScriptApp.deleteTrigger(t);
		}
	});
	SheetUtils.showAlert('Audit trigger removed.');
}

function getOrCreateShadowSheetFromAllSheets_(ss) {
	let shadow = ss.getSheetByName(CONFIG.AUDIT.SHADOW_SHEET_NAME);
	if (!shadow) {
		shadow = ss.insertSheet(CONFIG.AUDIT.SHADOW_SHEET_NAME);
		shadow.hideSheet();
	}

	// If shadow already has data, keep it as-is (baseline should not be mutated).
	if (shadow.getLastRow() >= 2) return shadow;

	const sheets = ss.getSheets();
	let shadowRows = [];
	let headers = null;
	let width = 0;

	for (let i = 0; i < sheets.length; i++) {
		const sh = sheets[i];
		const name = sh.getName();
		if (_shouldSkipAuditSheet_(name)) continue;
		const lastRow = sh.getLastRow();
		const lastCol = sh.getLastColumn();
		if (lastRow < 2 || lastCol < 1) continue;
		const data = sh.getRange(1, 1, lastRow, lastCol).getValues();
		if (!data || !data.length) continue;
		const emailIdCol = getEmailIdColumnIndex_(data[0]);
		if (emailIdCol <= 0) continue;

		if (!headers) {
			headers = data[0];
			width = headers.length;
			shadowRows.push(normalizeRowToWidth_(headers, width));
		}

		for (let r = 1; r < data.length; r++) {
			const emailId = String(data[r][emailIdCol - 1] || '').trim();
			if (!emailId) continue;
			shadowRows.push(normalizeRowToWidth_(data[r], width));
		}
	}

	if (shadowRows.length) {
		shadow.getRange(1, 1, shadowRows.length, shadowRows[0].length).setValues(shadowRows);
	}

	return shadow;
}

function normalizeRowToWidth_(row, width) {
	const w = Math.max(0, Number(width || 0));
	const arr = Array.isArray(row) ? row.slice(0, w) : [];
	while (arr.length < w) arr.push('');
	return arr;
}

function ensureShadowIncludesSheetRows_(shadow, sourceSheet) {
	if (!shadow || !sourceSheet) return;
	const shadowLastRow = shadow.getLastRow();
	if (shadowLastRow < 1) return;

	const shadowHeaders = shadow.getRange(1, 1, 1, shadow.getLastColumn()).getValues()[0];
	const shadowEmailIdCol = getEmailIdColumnIndex_(shadowHeaders);
	if (shadowEmailIdCol <= 0) return;

	const sheetLastRow = sourceSheet.getLastRow();
	const sheetLastCol = sourceSheet.getLastColumn();
	if (sheetLastRow < 2 || sheetLastCol < 1) return;
	const sheetData = sourceSheet.getRange(1, 1, sheetLastRow, sheetLastCol).getValues();
	const sheetEmailIdCol = getEmailIdColumnIndex_(sheetData[0]);
	if (sheetEmailIdCol <= 0) return;

	const existingIds = shadowLastRow >= 2
		? new Set(shadow.getRange(2, shadowEmailIdCol, shadowLastRow - 1, 1).getValues().flat().map(v => String(v || '').trim()).filter(Boolean))
		: new Set();

	const width = shadow.getLastColumn();
	const newRows = [];
	for (let r = 1; r < sheetData.length; r++) {
		const emailId = String(sheetData[r][sheetEmailIdCol - 1] || '').trim();
		if (!emailId) continue;
		if (existingIds.has(emailId)) continue;
		newRows.push(normalizeRowToWidth_(sheetData[r], width));
	}

	if (!newRows.length) return;
	shadow.getRange(shadow.getLastRow() + 1, 1, newRows.length, newRows[0].length).setValues(newRows);
}

function getOrCreateShadowSheet_(ss, sourceSheet) {
	let shadow = ss.getSheetByName(CONFIG.AUDIT.SHADOW_SHEET_NAME);
	if (!shadow) {
		shadow = ss.insertSheet(CONFIG.AUDIT.SHADOW_SHEET_NAME);
		shadow.hideSheet();

		// Copy headers and data rows with EmailID
		const data = sourceSheet.getDataRange().getValues();
		if (data.length && data[0].length) {
			const headers = data[0];
			const emailIdCol = getEmailIdColumnIndex_(headers);
			
			// Always include headers
			const shadowData = [headers];
			
			// Only include rows with non-empty EmailID
			if (emailIdCol > 0) {
				for (let i = 1; i < data.length; i++) {
					const emailId = String(data[i][emailIdCol - 1] || '').trim();
					if (emailId) {
						shadowData.push(data[i]);
					}
				}
			}
			
			shadow.getRange(1, 1, shadowData.length, shadowData[0].length).setValues(shadowData);
		}
		return shadow;
	}

	// Sync shadow: remove deleted rows and add new rows with EmailID
	const sourceData = sourceSheet.getDataRange().getValues();
	const headers = sourceData[0];
	const emailIdCol = getEmailIdColumnIndex_(headers);
	
	if (emailIdCol > 0) {
		// Get current shadow data
		const shadowLastRow = shadow.getLastRow();
		const shadowData = shadowLastRow > 1 
			? shadow.getRange(2, 1, shadowLastRow - 1, shadow.getLastColumn()).getValues()
			: [];
		
		const sourceDataRows = [];
		const shadowDataRows = [];
		
		// Build map of EmailIDs in source
		for (let i = 1; i < sourceData.length; i++) {
			const emailId = String(sourceData[i][emailIdCol - 1] || '').trim();
			if (emailId) {
				sourceDataRows.push({ emailId, data: sourceData[i] });
			}
		}
		
		// Build map of EmailIDs in shadow
		for (let i = 0; i < shadowData.length; i++) {
			const emailId = String(shadowData[i][emailIdCol - 1] || '').trim();
			if (emailId) {
				shadowDataRows.push({ emailId, data: shadowData[i] });
			}
		}
		
		// Remove rows from shadow that don't exist in source
		// BUT keep rows that have buffered audit records (not yet flushed)
		const sourceEmails = new Set(sourceDataRows.map(r => r.emailId));
		const bufferedEmailIds = getBufferedEmailIds_();
		let rowsToDelete = [];
		shadowDataRows.forEach((shadowRow, index) => {
			if (!sourceEmails.has(shadowRow.emailId) && !bufferedEmailIds.has(shadowRow.emailId)) {
				rowsToDelete.push(index + 2); // +1 for header, +1 for 0-based
			}
		});
		
		// Delete in reverse order to avoid index shifting
		for (let i = rowsToDelete.length - 1; i >= 0; i--) {
			shadow.deleteRow(rowsToDelete[i]);
		}
		
		// Add new rows from source that don't exist in shadow
		const shadowEmails = new Set(shadowDataRows.map(r => r.emailId));
		const newRows = sourceDataRows.filter(r => !shadowEmails.has(r.emailId));
		
		if (newRows.length > 0) {
			const insertRow = shadow.getLastRow() + 1;
			const newRowData = newRows.map(r => r.data);
			shadow.getRange(insertRow, 1, newRows.length, headers.length).setValues(newRowData);
		}
	}

	return shadow;
}

function resolveShadowRow_(shadow, emailIdCol, emailId, fallbackRowIndex) {
  if (emailIdCol > 0 && emailId) {
    const lastRow = shadow.getLastRow();
    if (lastRow >= 2) {
      const ids = shadow.getRange(2, emailIdCol, lastRow - 1, 1).getValues().flat();
      const matchIndex = ids.findIndex(id => String(id).trim() === String(emailId).trim());
      if (matchIndex !== -1) {
        return { rowIndex: matchIndex + 2, matched: true };
      }
    }
  }
  return { rowIndex: fallbackRowIndex, matched: false };
}
function getFieldModesFromSchema_() {
	const modes = {};
	try {
		// Try to load schema from PropertiesService cache first
		const props = PropertiesService.getUserProperties();
		const cached = props.getProperty('SCHEMA_FIELD_MODES_CACHE');
		if (cached) {
			return JSON.parse(cached);
		}
		
		// Load schema from docs/schema.json via DriveApp
		const files = DriveApp.getFilesByName('schema.json');
		while (files.hasNext()) {
			const file = files.next();
			const parent = file.getParents();
			// Check if it's in docs folder
			if (parent.hasNext()) {
				const parentFolder = parent.next();
				if (parentFolder.getName() === 'docs') {
					const content = file.getBlob().getDataAsString();
					const schema = JSON.parse(content);
					
					// Build field mode map
					schema.forEach(field => {
						modes[field.name] = field.mode || 'NULLABLE';
					});
					
					// Cache for 1 hour
					props.setProperty('SCHEMA_FIELD_MODES_CACHE', JSON.stringify(modes));
					return modes;
				}
			}
		}
	} catch (e) {
		Logger.log('Error loading schema: ' + e);
	}
	
	// Default: treat unknown fields as NULLABLE
	return {};
}

/**
 * Gets set of EmailIDs that have buffered audit records
 * @private
 */
function getBufferedEmailIds_() {
	const props = PropertiesService.getDocumentProperties();
	const existing = props.getProperty('AUDIT_BUFFER');
	if (!existing) return new Set();
	
	try {
		const buffer = JSON.parse(existing);
		return new Set(buffer.map(r => String(r.emailId || '').trim()));
	} catch (e) {
		return new Set();
	}
}

function sendAuditRecords_(records) {
	const endpoint = (CONFIG.AUDIT.ENDPOINT && CONFIG.AUDIT.ENDPOINT.trim())
		? CONFIG.AUDIT.ENDPOINT.trim()
		: CONFIG.CLOUD_RUN_BASE_URL + '/audit/review_edits';

	const token = ScriptApp.getOAuthToken();
	const payload = JSON.stringify({ records: records });

	try {
		const resp = UrlFetchApp.fetch(endpoint, {
			method: 'post',
			contentType: 'application/json',
			headers: { Authorization: 'Bearer ' + token },
			payload: payload,
			muteHttpExceptions: true
		});

		const code = resp.getResponseCode();
		const bodyText = resp.getContentText() || '';
		if (code < 200 || code >= 300) {
			Logger.log('Audit log failed: ' + code + ' ' + bodyText);
			return false;
		}

		let body = null;
		try {
			body = bodyText ? JSON.parse(bodyText) : null;
		} catch (e) {
			Logger.log('Audit log response parse failed: ' + e + '; body=' + bodyText);
			return false;
		}

		const insertedCount = body && body.recordCount != null ? Number(body.recordCount) : NaN;
		const ok = body && body.ok === true;
		const confirmed = ok || (!isNaN(insertedCount) && insertedCount === records.length);

		if (!confirmed) {
			Logger.log(
				'Audit log response missing success confirmation; retaining buffer. code=' +
				code +
				' body=' +
				bodyText
			);
			return false;
		}

		Logger.log('Audit log confirmed: inserted ' + records.length + ' records');
		return true;
	} catch (e) {
		Logger.log('Audit log request failed: ' + e);
		return false;
	}
}

function getEditorEmail_() {
	const active = Session.getActiveUser().getEmail();
	if (active) return active;
	const effective = Session.getEffectiveUser().getEmail();
	return effective || 'unknown';
}

function getEmailIdColumnIndex_(headers) {
	const normalized = (headers || []).map(h => String(h).trim().toLowerCase());
	const candidates = ['emailids', 'email ids', 'email_id', 'emailid', 'email id'];
	for (let i = 0; i < candidates.length; i++) {
		const idx = normalized.indexOf(candidates[i]);
		if (idx !== -1) return idx + 1;
	}
	return -1;
}

function getAuditBatchConfig_() {
	const audit = CONFIG && CONFIG.AUDIT ? CONFIG.AUDIT : {};
	return {
		batchSize: audit.BATCH_SIZE || 100,
		flushIntervalSeconds: audit.FLUSH_INTERVAL_SECONDS || 60
	};
}

function bufferAuditRecords_(records) {
	const props = PropertiesService.getDocumentProperties();
	const existing = props.getProperty('AUDIT_BUFFER');
	let buffer = [];
	if (existing) {
		try {
			buffer = JSON.parse(existing);
		} catch (e) {
			buffer = [];
		}
	}

	const merged = mergeAuditRecords_(buffer, records);
	props.setProperty('AUDIT_BUFFER', JSON.stringify(merged));
}

function mergeAuditRecords_(existing, incoming) {
	const merged = [];
	const indexByKey = {};

	const all = (existing || []).concat(incoming || []);
	all.forEach(record => {
		const key = buildAuditKey_(record);
		const idx = indexByKey[key];
		if (idx === undefined) {
			indexByKey[key] = merged.length;
			merged.push({
				timestamp: record.timestamp,
				editor: record.editor,
				emailId: record.emailId,
				modifications: record.modifications || []
			});
			return;
		}

		const current = merged[idx];
		current.timestamp = record.timestamp;
		
		// Merge modifications: for same column, keep first oldValue, use latest newValue
		if (record.modifications && Array.isArray(record.modifications)) {
			const modByColumn = {};
			
			// Process existing modifications
			current.modifications.forEach(mod => {
				const key = mod.columnName;
				modByColumn[key] = mod;
			});
			
			// Process new modifications - update newValue, keep original oldValue
			record.modifications.forEach(mod => {
				const key = mod.columnName;
				if (modByColumn[key]) {
					// Column already modified - keep old oldValue, update newValue
					modByColumn[key].newValue = mod.newValue;
					modByColumn[key].columnName = mod.columnName; // update in case it changed
				} else {
					// New column modification
					modByColumn[key] = mod;
				}
			});
			
			current.modifications = Object.values(modByColumn);
		}
	});

	return merged;
}

function buildAuditKey_(record) {
	const emailId = String(record.emailId || '').trim();
	const editor = String(record.editor || '').trim();
	return editor ? (emailId + '|' + editor) : emailId;
}

function flushAuditBuffer_(force) {
	const props = PropertiesService.getDocumentProperties();
	const config = getAuditBatchConfig_();
	const nowMs = Date.now();

	const lastFlushMs = Number(props.getProperty('AUDIT_LAST_FLUSH_MS') || '0');
	const elapsedSeconds = (nowMs - lastFlushMs) / 1000;

	const existing = props.getProperty('AUDIT_BUFFER');
	if (!existing) return;

	let buffer = [];
	try {
		buffer = JSON.parse(existing);
	} catch (e) {
		buffer = [];
	}

	if (!buffer.length) return;

	if (!force && buffer.length < config.batchSize && elapsedSeconds < config.flushIntervalSeconds) {
		return;
	}

	let remaining = buffer;
	let sentAny = false;

	while (remaining.length) {
		const batch = remaining.slice(0, config.batchSize);
		const ok = sendAuditRecords_(batch);
		if (!ok) {
			Logger.log('Audit flush stopped; retaining ' + remaining.length + ' buffered records');
			break;
		}
		sentAny = true;
		remaining = remaining.slice(config.batchSize);
	}

	if (sentAny) {
		props.setProperty('AUDIT_LAST_FLUSH_MS', String(nowMs));
	}

	if (remaining.length) {
		props.setProperty('AUDIT_BUFFER', JSON.stringify(remaining));
	} else {
		props.deleteProperty('AUDIT_BUFFER');
	}
}

function flushAuditNow() {
	flushAuditBuffer_(true);
}

/**
 * Debug function to check audit buffer contents
 */
function checkAuditBuffer() {
	const props = PropertiesService.getDocumentProperties();
	const existing = props.getProperty('AUDIT_BUFFER');
	const ui = SpreadsheetApp.getUi();
	
	if (!existing) {
		Logger.log('Audit buffer is empty');
		ui.alert('Audit Buffer', 'The audit buffer is empty.', ui.ButtonSet.OK);
		return;
	}
	
	try {
		const buffer = JSON.parse(existing);
		Logger.log('Audit buffer contains ' + buffer.length + ' records:');
		let message = 'Buffer contains ' + buffer.length + ' records:\n\n';
		
		buffer.slice(0, 5).forEach((record, index) => {
			Logger.log('Record ' + (index + 1) + ': EmailID=' + record.emailId + ', Modifications=' + record.modifications.length);
			message += 'Record ' + (index + 1) + ':\n';
			message += '  EmailID: ' + record.emailId + '\n';
			message += '  Modifications: ' + record.modifications.length + '\n\n';
		});
		
		if (buffer.length > 5) {
			message += '... and ' + (buffer.length - 5) + ' more records (see Logs)';
		}
		
		ui.alert('Audit Buffer', message, ui.ButtonSet.OK);
	} catch (e) {
		Logger.log('Failed to parse audit buffer: ' + e);
		ui.alert('Error', 'Failed to parse audit buffer: ' + e, ui.ButtonSet.OK);
	}
}

/**
 * Debug function to clear the audit buffer
 */
function clearAuditBuffer() {
	const ui = SpreadsheetApp.getUi();
	const response = ui.alert(
		'Clear Audit Buffer',
		'Are you sure you want to clear all buffered audit records? This cannot be undone.',
		ui.ButtonSet.YES_NO
	);
	
	if (response === ui.Button.YES) {
		PropertiesService.getDocumentProperties().deleteProperty('AUDIT_BUFFER');
		Logger.log('Audit buffer cleared');
		ui.alert('Success', 'Audit buffer has been cleared.', ui.ButtonSet.OK);
	}
}

/**
 * Debug function to test audit flush with mock EmailIDs
 */
function testAuditFlush() {
	const props = PropertiesService.getDocumentProperties();
	const existing = props.getProperty('AUDIT_BUFFER');
	const ui = SpreadsheetApp.getUi();
	
	if (!existing) {
		Logger.log('Audit buffer is empty - nothing to test');
		ui.alert('Test Audit Flush', 'The audit buffer is empty. Make an edit first.', ui.ButtonSet.OK);
		return;
	}
	
	try {
		const buffer = JSON.parse(existing);
		Logger.log('Testing audit flush for ' + buffer.length + ' buffered records');
		flushAuditNow();
		
		ui.alert(
			'Test Audit Flush',
			'Attempted to flush ' + buffer.length + ' buffered records.\n\n' +
			'Check Apps Script logs (View > Logs) for details.',
			ui.ButtonSet.OK
		);
	} catch (e) {
		Logger.log('Test audit flush failed: ' + e);
		ui.alert('Error', 'Test failed: ' + e, ui.ButtonSet.OK);
	}
}