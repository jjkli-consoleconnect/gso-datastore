const PROJECT_ID = 'pccw-internal-virt-agent-uat';
const DATASET_ID = 'Admin';
const LOOKUP_TABLE_ID = 'DataStudioReportLookup';
const REPORT_MIME_TYPES = [
  'application/vnd.google-apps.datastudio',
  'application/vnd.google-apps.looker-studio'
];

function syncLookerStudioReportNamesToBigQuery() {
  ensureLookupTableExists_();

  const reports = listReportIdsOnlyFromBigQuery_();
  console.log('BigQuery usage IDs discovered: ' + reports.length);

  if (!reports.length) {
    console.log('No Looker Studio report IDs found in BigQuery usage for this account.');
    return;
  }

  const driveTitlesById = listAccessibleLookerStudioReportTitlesById_();
  const enrichedReports = reports.map(function(report) {
    const resolvedName = resolveLookerStudioReportName_(report.looker_studio_report_id, driveTitlesById);
    return {
      looker_studio_report_id: report.looker_studio_report_id,
      report_name: resolvedName
    };
  });

  const namedReports = enrichedReports.filter(function(report) {
    return !!report.report_name;
  }).length;
  console.log('Drive report titles resolved: ' + namedReports + ' of ' + enrichedReports.length);

  if (!namedReports) {
    console.log('No report titles were resolved from Drive. Existing manual names in the lookup table will be preserved.');
  }

  const batchSize = 200;
  let totalMerged = 0;

  for (let i = 0; i < enrichedReports.length; i += batchSize) {
    const batch = enrichedReports.slice(i, i + batchSize);
    const merged = mergeReportBatch_(batch);
    totalMerged += merged;
  }

  console.log('Sync complete. Reports scanned: ' + enrichedReports.length + ', rows merged: ' + totalMerged);
}

function setupDailySyncTrigger() {
  deleteExistingSyncTriggers_();
  ScriptApp.newTrigger('syncLookerStudioReportNamesToBigQuery')
    .timeBased()
    .everyDays(1)
    .atHour(3)
    .create();

  console.log('Daily trigger created at ~03:00 local script timezone.');
}

function deleteExistingSyncTriggers_() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'syncLookerStudioReportNamesToBigQuery') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function listReportsViaBigQueryUsageIds_() {
  const ids = getRecentReportIdsFromBigQuery_(300);
  if (!ids.length) {
    console.log('BigQuery usage fallback found 0 report IDs.');
    return [];
  }

  const reports = [];
  ids.forEach(function(reportId) {
    reports.push({
      looker_studio_report_id: reportId,
      report_name: ''
    });
  });

  console.log('BigQuery usage fallback IDs: ' + ids.length + ', names unresolved in Drive: ' + ids.length);
  return reports;
}

function listReportIdsOnlyFromBigQuery_() {
  const ids = getRecentReportIdsFromBigQuery_(500);
  return ids.map(function(reportId) {
    return {
      looker_studio_report_id: reportId,
      report_name: ''
    };
  });
}

function listAccessibleLookerStudioReportTitlesById_() {
  const titlesById = {};
  const mimeTypeFilters = REPORT_MIME_TYPES.map(function(mimeType) {
    return "mimeType = '" + mimeType + "'";
  }).join(' or ');
  const query = 'trashed = false and (' + mimeTypeFilters + ')';
  const request = {
    q: query,
    corpora: 'allDrives',
    includeItemsFromAllDrives: true,
    supportsAllDrives: true,
    maxResults: 1000
  };

  let pageToken;
  let totalFiles = 0;

  do {
    if (pageToken) {
      request.pageToken = pageToken;
    } else {
      delete request.pageToken;
    }

    const response = Drive.Files.list(request);
    const files = response.items || [];

    files.forEach(function(file) {
      if (file && file.id) {
        titlesById[file.id] = file.title || '';
        totalFiles++;
      }
    });

    pageToken = response.nextPageToken;
  } while (pageToken);

  console.log('Drive scan completed. Accessible Looker Studio files found: ' + totalFiles);
  return titlesById;
}

function resolveLookerStudioReportName_(reportId, titlesById) {
  if (titlesById && titlesById[reportId]) {
    return titlesById[reportId];
  }

  return '';
}

function getRecentReportIdsFromBigQuery_(limit) {
  const sql =
    'SELECT looker_studio_report_id ' +
    'FROM `' + PROJECT_ID + '.' + DATASET_ID + '.DataStudioUsage` ' +
    'WHERE looker_studio_report_id IS NOT NULL ' +
    'GROUP BY looker_studio_report_id ' +
    'ORDER BY MAX(creation_time) DESC ' +
    'LIMIT ' + String(limit || 100);

  const request = {
    query: sql,
    useLegacySql: false
  };

  const queryResults = BigQuery.Jobs.query(request, PROJECT_ID);
  const rows = queryResults.rows || [];

  const ids = rows
    .map(function(r) { return r.f && r.f[0] ? r.f[0].v : null; })
    .filter(function(v) { return !!v; });

  return ids;
}

function ensureLookupTableExists_() {
  try {
    BigQuery.Tables.get(PROJECT_ID, DATASET_ID, LOOKUP_TABLE_ID);
  } catch (err) {
    const tableResource = {
      tableReference: {
        projectId: PROJECT_ID,
        datasetId: DATASET_ID,
        tableId: LOOKUP_TABLE_ID
      },
      schema: {
        fields: [
          { name: 'looker_studio_report_id', type: 'STRING', mode: 'REQUIRED' },
          { name: 'report_name', type: 'STRING', mode: 'NULLABLE' },
          { name: 'first_seen_at', type: 'TIMESTAMP', mode: 'NULLABLE' },
          { name: 'last_seen_at', type: 'TIMESTAMP', mode: 'NULLABLE' },
          { name: 'updated_at', type: 'TIMESTAMP', mode: 'NULLABLE' }
        ]
      }
    };

    BigQuery.Tables.insert(tableResource, PROJECT_ID, DATASET_ID);
    console.log('Created lookup table: ' + PROJECT_ID + '.' + DATASET_ID + '.' + LOOKUP_TABLE_ID);
  }
}

function mergeReportBatch_(batch) {
  const structs = batch.map(function(r) {
    return "STRUCT('" + escapeSql_(r.looker_studio_report_id) + "' AS looker_studio_report_id, '" +
      escapeSql_(r.report_name) + "' AS report_name)";
  }).join(',\n    ');

  const query = "MERGE `" + PROJECT_ID + '.' + DATASET_ID + '.' + LOOKUP_TABLE_ID + "` t\n" +
    "USING (SELECT * FROM UNNEST([\n    " + structs + "\n  ])) s\n" +
    "ON t.looker_studio_report_id = s.looker_studio_report_id\n" +
    "WHEN MATCHED THEN\n" +
    "  UPDATE SET\n" +
    "    t.report_name = CASE WHEN s.report_name IS NOT NULL AND s.report_name != '' THEN s.report_name ELSE t.report_name END,\n" +
    "    t.updated_at = CURRENT_TIMESTAMP()\n" +
    "WHEN NOT MATCHED THEN\n" +
    "  INSERT (looker_studio_report_id, report_name, first_seen_at, last_seen_at, updated_at)\n" +
    "  VALUES (s.looker_studio_report_id, s.report_name, NULL, NULL, CURRENT_TIMESTAMP());";

  const req = {
    query: query,
    useLegacySql: false
  };

  const job = BigQuery.Jobs.query(req, PROJECT_ID);
  waitForQueryJob_(job.jobReference.jobId);

  return batch.length;
}

function waitForQueryJob_(jobId) {
  let tries = 0;
  while (tries < 60) {
    const job = BigQuery.Jobs.get(PROJECT_ID, jobId);
    if (job.status && job.status.state === 'DONE') {
      if (job.status.errorResult) {
        throw new Error('BigQuery MERGE failed: ' + job.status.errorResult.message);
      }
      return;
    }
    Utilities.sleep(2000);
    tries++;
  }
  throw new Error('Timed out waiting for BigQuery job: ' + jobId);
}

function escapeSql_(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value).replace(/'/g, "''");
}

function diagnoseLookerStudioDiscovery() {
  const viaBq = listReportsViaBigQueryUsageIds_();
  const driveTitlesById = listAccessibleLookerStudioReportTitlesById_();
  console.log('Diagnostics - BigQuery IDs: ' + viaBq.length + ', Drive titles: ' + Object.keys(driveTitlesById).length + '.');
}
