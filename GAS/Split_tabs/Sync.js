/**
 * Sync Service (Audit)
 *
 * This file intentionally contains ONLY the workflow for syncing audit logs
 * (reviewer edits) to BigQuery via the Cloud Run backend.
 *
 * Outage/record sync is not managed by Apps Script.
 */

/**
 * Flush any buffered audit edits to BigQuery.
 *
 * Intended to be called at the end of other workflows (e.g. consolidateAllSimple)
 * so that reviewer edits are not left sitting in the buffer.
 *
 * @param {Object=} meta Optional context for logging.
 */
function syncAuditAfterConsolidation(meta) {
  try {
    const ctx = meta || {};
    Logger.log(
      'syncAuditAfterConsolidation: reason=%s rowsWritten=%s sheetsScanned=%s target=%s',
      String(ctx.reason || ''),
      String(ctx.rowsWritten || ''),
      String(ctx.sheetsScanned || ''),
      String(ctx.targetSheetName || '')
    );

    if (typeof flushAuditNow === 'function') {
      flushAuditNow();
      return true;
    }

    // Fallback (should not normally happen): call the internal flush directly if available.
    if (typeof flushAuditBuffer_ === 'function') {
      flushAuditBuffer_(true);
      return true;
    }

    Logger.log('syncAuditAfterConsolidation: audit flush functions not available');
    return false;
  } catch (e) {
    Logger.log('syncAuditAfterConsolidation failed: ' + e);
    return false;
  }
}

/**
 * Manual command for admins: flush audit buffer now.
 */
function syncAuditNow() {
  return syncAuditAfterConsolidation({ reason: 'syncAuditNow' });
}

// Intentionally no record-sync functions in this file.
