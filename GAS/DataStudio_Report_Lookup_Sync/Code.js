// --- GLOBAL VARIABLES ---
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'Admin';
var tableId = 'DataStudioReportLookup';

// Error notifications
var errorNotificationEmails = 'jjkli@consoleconnect.com';

// Data Studio (Looker Studio) API endpoint
var DS_API_BASE = 'https://datastudio.googleapis.com/v1';
// Quota project where the Data Studio API is enabled (verified working).
var QUOTA_PROJECT = 'pccw-internal-virt-agent-uat';

/**
 * Lists all Looker Studio REPORT assets visible to the authenticated user,
 * then upserts id -> name into Admin.DataStudioReportLookup.
 *
 * Setup:
 *   1. Run as a user who can see all reports (Looker Studio admin/owner).
 *   2. Apps Script manifest/appsscript.json scopes:
 *        https://www.googleapis.com/auth/datastudio
 *        https://www.googleapis.com/auth/bigquery
 *        https://www.googleapis.com/auth/script.external_request
 *   3. Enable the BigQuery Advanced Service in the script.
 *   4. Run setupDailyTrigger() once.
 */
function syncReportLookup() {
  try {
    var reports = listAllReports();
    if (reports.length === 0) {
      console.log('No reports found - nothing to sync.');
      return;
    }
    var merged = upsertToBigQuery(reports);
    console.log('Synced ' + merged + ' report names into ' + datasetId + '.' + tableId);
  } catch (err) {
    console.error('syncReportLookup failed: ' + (err && err.stack ? err.stack : err));
    notifyError('DataStudio Report Lookup Sync failed', err);
    throw err;
  }
}

/** Paginates through the Data Studio assets:search endpoint. */
function listAllReports() {
  var token = ScriptApp.getOAuthToken();
  var reports = [];
  var pageToken = '';

  do {
    var url = DS_API_BASE + '/assets:search?assetTypes=REPORT&pageSize=200' +
      (pageToken ? '&pageToken=' + encodeURIComponent(pageToken) : '');
    var response = UrlFetchApp.fetch(url, {
      headers: {
        Authorization: 'Bearer ' + token,
        'x-goog-user-project': QUOTA_PROJECT
      },
      muteHttpExceptions: true
    });
    if (response.getResponseCode() !== 200) {
      throw new Error('assets:search failed HTTP ' + response.getResponseCode() +
        ': ' + response.getContentText());
    }
    var payload = JSON.parse(response.getContentText());
    (payload.assets || []).forEach(function (asset) {
      // Verified fields: asset.name = report id (uuid), asset.title = report name
      if (asset.assetType === 'REPORT' && asset.name) {
        reports.push({
          id: asset.name,
          name: asset.title || '(unnamed)'
        });
      }
    });
    pageToken = payload.nextPageToken || '';
  } while (pageToken);

  console.log('Found ' + reports.length + ' reports.');
  return reports;
}

/** MERGEs report id/name pairs into Admin.DataStudioReportLookup. Returns affected rows. */
function upsertToBigQuery(reports) {
  var mergeSql =
    "MERGE `" + projectId + "." + datasetId + "." + tableId + "` T " +
    "USING (" + rowsSql(reports) + ") S " +
    "ON T.looker_studio_report_id = S.looker_studio_report_id " +
    "WHEN MATCHED AND IFNULL(T.report_name,'') != S.report_name THEN " +
    "  UPDATE SET report_name = S.report_name, last_seen_at = CURRENT_TIMESTAMP(), updated_at = CURRENT_TIMESTAMP() " +
    "WHEN MATCHED THEN " +
    "  UPDATE SET last_seen_at = CURRENT_TIMESTAMP() " +
    "WHEN NOT MATCHED THEN " +
    "  INSERT (looker_studio_report_id, report_name, first_seen_at, last_seen_at, updated_at) " +
    "  VALUES (S.looker_studio_report_id, S.report_name, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())";

  // Advanced Service QueryRequest. location=EU is required: the lookup table
  // lives in the EU multi-region and jobs.query defaults to US otherwise.
  var request = {
    query: mergeSql,
    useLegacySql: false,
    priority: 'INTERACTIVE',
    location: 'EU'
  };
  var response = BigQuery.Jobs.query(request, projectId);
  while (!response.jobComplete) {
    Utilities.sleep(1000);
    response = BigQuery.Jobs.getQueryResults(projectId, response.jobReference.jobId, { location: 'EU' });
  }
  // MERGE is DML: affected row count comes from numDmlAffectedRows
  return Number(response.numDmlAffectedRows || 0);
}

/** Builds "SELECT id, name" rows; first row carries column aliases. Verified syntax. */
function rowsSql(reports) {
  return reports.map(function (r, i) {
    var name = String(r.name).replace(/\\/g, '\\\\').replace(/'/g, "''");
    if (i === 0) {
      return "SELECT '" + r.id + "' AS looker_studio_report_id, '" + name + "' AS report_name";
    }
    return "SELECT '" + r.id + "', '" + name + "'";
  }).join(' UNION ALL ');
}

/** Creates a daily trigger (idempotent). Run once manually. */
function setupDailyTrigger() {
  var existing = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === 'syncReportLookup';
  });
  if (!existing) {
    ScriptApp.newTrigger('syncReportLookup').timeBased().everyDays(1).atHour(2).create();
    console.log('Daily trigger created.');
  } else {
    console.log('Daily trigger already exists.');
  }
}

function notifyError(subject, err) {
  try {
    MailApp.sendEmail(errorNotificationEmails, subject,
      'Error: ' + (err && err.message ? err.message : String(err)));
  } catch (e) {
    console.error('Failed to send error email: ' + e);
  }
}
