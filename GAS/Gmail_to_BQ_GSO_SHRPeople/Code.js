// --- GLOBAL VARIABLES ---
var subject = 'BQ - GSO.SHR:People';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'CloudWatch';
var VERBOSE = true; // extra logs for tracing

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'GSO';
var tableId = 'SHRPeople';

// Google Drive folder details
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA';

// Error notifications
var errorNotificationEmails = 'aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';

// Archive Label
var archivedLabel = 'ArchivedReports';

// Centralized PipelineRuns logging
var pipelineRunsDatasetId = 'GSO';
var pipelineRunsTableId = 'PipelineRuns';
var scriptName = 'Gmail_to_BQ_GSO_SHRPeople';
var currentRunId = null;

// --- FUNCTIONS ---
function searchForEmailAndAttachments() {
  if (!currentRunId) {
    currentRunId = Utilities.getUuid();
    logPipelineRun(scriptName, currentRunId, 'RUNNING', 'INFO', 'Pipeline run started', null, null, null, null, null);
  }
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label;
  var threads = GmailApp.search(searchQuery);
  console.log("Number of emails found:", threads.length);
  if (VERBOSE) {
    for (var ti = 0; ti < threads.length; ti++) {
      var th = threads[ti];
      console.log('[Thread]', ti + 1, '/', threads.length, 'id=', th.getId(), 'subject="' + th.getFirstMessageSubject() + '"', 'lastDate=', th.getLastMessageDate());
    }
  }

  if (threads.length === 0) {
    console.log('No emails found with the given search query.');
  logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'No matching emails. Nothing to do.', null, null, 0, null, null);
    return;
  }

  // Process ALL matching threads/messages/attachments
  var tempTableId = 'SHRPeople_tmp_' + Utilities.getUuid().replace(/-/g, '').substring(0, 18);
  var attachmentsProcessed = 0;
  var perAttachmentCounts = [];
  var failedAttachments = [];
  var dashboardLabelObj = GmailApp.getUserLabelByName(label);
  var archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);

  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  for (var t = 0; t < threads.length; t++) {
    var thread = threads[t];
    var messages = thread.getMessages();
    if (VERBOSE) console.log('[Thread]', t + 1, '/', threads.length, 'id=', thread.getId(), 'messages=', messages.length);
    var threadOk = true;
    try {
      for (var m = 0; m < messages.length; m++) {
        var message = messages[m];
        var attachments = message.getAttachments();
        if (VERBOSE) console.log('  [Message]', m + 1, '/', messages.length, 'id=', message.getId(), 'date=', message.getDate(), 'attachments=', (attachments ? attachments.length : 0));
        if (!attachments || attachments.length === 0) continue;
        for (var j = 0; j < attachments.length; j++) {
          var att = attachments[j];
          if (VERBOSE) console.log('    [Attachment]', j + 1, '/', attachments.length, 'name="' + att.getName() + '"', 'size=', (att.getSize ? att.getSize() : '?'), 'bytes');
          try {
            var res = loadAttachmentToTemp(att, tempTableId, attachmentsProcessed === 0);
            attachmentsProcessed++;
            perAttachmentCounts.push({ name: att.getName(), rows: res.rows, jobId: res.jobId });
            if (VERBOSE) console.log('      -> loaded rows=', res.rows, 'jobId=', res.jobId);
          } catch (e) {
            threadOk = false;
            failedAttachments.push({ name: att.getName(), error: e.message });
            console.error('Failed processing attachment ' + att.getName() + ': ' + e.message);
          }
        }
      }
    } catch (err) {
      threadOk = false;
      console.error('Error processing thread: ' + err.message);
    }

    // Label handling per thread if processed without errors
    if (threadOk) {
      if (dashboardLabelObj) {
        thread.removeLabel(dashboardLabelObj);
        console.log('Label "' + label + '" removed from email thread.');
      }
      if (archivedLabelObj) {
        thread.addLabel(archivedLabelObj);
        console.log('Label "' + archivedLabel + '" added to email thread.');
      }
    }
  }

  if (attachmentsProcessed === 0) {
    console.log('No attachments to load across all matching emails.');
    return;
  }

  // MERGE temp into target by SRNo (non-null)
  try {
    runMergeTempIntoTarget(tempTableId);
    console.log('MERGE completed into ' + datasetId + '.' + tableId);
  } catch (mergeErr) {
    console.error('MERGE failed: ' + mergeErr.message);
    throw mergeErr;
  } finally {
    // Drop temp table best effort
    try { dropTempTable(tempTableId); } catch (dropErr) { console.warn('Temp drop failed: ' + dropErr.message); }
  }

  // Log summary
  var summary = {
    tempTableId: tempTableId,
    attachmentsProcessed: attachmentsProcessed,
    perAttachmentCounts: perAttachmentCounts,
    failedAttachments: failedAttachments
  };

  // Legacy PipelineLogs write removed; using PipelineRuns instead.
  // Summary to PipelineRuns (best-effort rowsMerged = total across attachments)
  var totalRows = 0;
  try { totalRows = perAttachmentCounts.reduce(function(acc, x){ return acc + (x && x.rows ? x.rows : 0); }, 0); } catch (_) {}
  logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'Data pipeline run complete.', null, null, totalRows, null, null);
}

function processAttachment(attachment) {
  try {
    if (attachment) {
      var csvData = Utilities.parseCsv(attachment.getDataAsString());
      csvData.shift(); // remove header row
      csvData = csvData.filter(row => row.some(cell => cell !== ''));

      var transformedData = csvData.map(row => {
        return [
          row[0],  // CustID
          row[1],  // CustName
          row[2],  // SRNo
          row[3],  // Product Family
          row[4],  // Product ID
          row[5],  // Insight Circuit ID
          row[6],  // Circuit Owner
          row[7],  // ProductDescription
          row[8]   // SR Status
        ];
      });

      var processedCsvContent = transformedData.map(row => row.join(',')).join('\n');
      var originalFileName = attachment.getName();
      var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv';

      var file = DriveApp.getFolderById(folderId).createFile(fileName, processedCsvContent);
      console.log('Processed CSV file saved to Google Drive:', file.getUrl());

      var job = {
        configuration: {
          load: {
            destinationTable: {
              projectId: projectId,
              datasetId: datasetId,
              tableId: tableId
            },
            sourceFormat: 'CSV',
            skipLeadingRows: 0,
            writeDisposition: 'WRITE_TRUNCATE'
          }
        }
      };

      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(processedCsvContent));
      console.log("CSV data updated in BigQuery table successfully!");

      deleteCsvFile(fileName, folderId);

    } else {
      console.log("No attachment found in this email.");
    }

  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack);
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: 'Error in Automated Script',
      body: 'An error occurred while processing the attachment: \n\n' + error.message + '\n\n' + error.stack
    });
  logPipelineRun(scriptName, currentRunId, 'ERROR', 'ERROR', 'Error processing attachment: ' + error.message, null, null, null, null, null);
  }
}

function deleteCsvFile(fileName, folderId) {
  var folder = DriveApp.getFolderById(folderId);
  var amendedFile = folder.getFilesByName(fileName);
  if (amendedFile.hasNext()) {
    amendedFile.next().setTrashed(true);
    console.log("Amended CSV file deleted from Google Drive.");
  } else {
    console.log("Amended CSV file not found.");
  }
}

function logToBigQuery(datasetId, tableId, pipelineName, runId, logLevel, message, FunctionName, BatchID, Details) {
  // Retain legacy function for now to avoid breaking callers; no changes
  var projectId = 'pccw-internal-virt-agent-uat';
  var accessToken = ScriptApp.getOAuthToken();
  var url = 'https://bigquery.googleapis.com/bigquery/v2/projects/' + projectId +
            '/datasets/' + datasetId + '/tables/' + tableId + '/insertAll';

  var row = { json: { Timestamp: new Date().toISOString(), PipelineName: pipelineName, RunID: runId, LogLevel: logLevel, Message: message, FunctionName: FunctionName, BatchID: BatchID, Details: Details } };
  var payload = { rows: [row] };
  var options = { method: 'post', contentType: 'application/json', headers: { Authorization: 'Bearer ' + accessToken }, payload: JSON.stringify(payload), muteHttpExceptions: true };
  try { UrlFetchApp.fetch(url, options); } catch (e) { console.warn('Legacy logToBigQuery failed: ' + e.message); }
}

// New centralized PipelineRuns logger using MERGE
function logPipelineRun(pipelineName, runId, status, logLevel, message, windowStartIso, windowEndIso, rowsMerged, errorCode, contextObj) {
  try {
    var wsExpr = windowStartIso ? ("TIMESTAMP('" + windowStartIso + "')") : 'NULL';
    var weExpr = windowEndIso ? ("TIMESTAMP('" + windowEndIso + "')") : 'NULL';
    var rmExpr = (rowsMerged === 0 || rowsMerged) ? String(rowsMerged) : 'NULL';
    var ecExpr = errorCode ? ("'" + escapeSqlLiteral(String(errorCode)) + "'") : 'NULL';
    var lvl = logLevel ? escapeSqlLiteral(String(logLevel)) : '';
    var msg = message ? escapeSqlLiteral(String(message)) : '';
    var pname = escapeSqlLiteral(String(pipelineName));
    var rid = escapeSqlLiteral(String(runId));
    var stat = escapeSqlLiteral(String(status));
    var query = "\n      MERGE `" + projectId + "." + pipelineRunsDatasetId + "." + pipelineRunsTableId + "` T\n      USING (SELECT '" + pname + "' AS PipelineName, '" + rid + "' AS RunID) S\n      ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID\n      WHEN MATCHED THEN UPDATE SET\n        RunTime = CURRENT_TIMESTAMP(),\n        WindowStart = " + wsExpr + ",\n        WindowEnd = " + weExpr + ",\n        RowsMerged = " + rmExpr + ",\n        LogLevel = '" + lvl + "',\n        Message = '" + msg + "',\n        Status = '" + stat + "',\n        ErrorCode = " + ecExpr + ",\n        Context = CAST(NULL AS JSON)\n      WHEN NOT MATCHED THEN\n        INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, Context)\n        VALUES (CURRENT_TIMESTAMP(), '" + pname + "', " + wsExpr + ", " + weExpr + ", " + rmExpr + ", '" + lvl + "', '" + msg + "', '" + rid + "', '" + stat + "', " + ecExpr + ", CAST(NULL AS JSON));\n    ";
    var job = BigQuery.Jobs.insert({ configuration: { query: { query: query, useLegacySql: false } } }, projectId);
    waitForJobCompletion(job);
  } catch (e) {
    console.warn('logPipelineRun failed: ' + e.message);
  }
}

function escapeSqlLiteral(s) { return s.replace(/'/g, "''"); }

// === Helpers ===
function getSchemaFields() {
  return [
  { name: 'CustID', type: 'STRING' },
  { name: 'CustName', type: 'STRING' },
  { name: 'SRNo', type: 'STRING' },
  { name: 'Product Family', type: 'STRING' },
  { name: 'Product ID', type: 'STRING' },
  { name: 'Insight Circuit ID', type: 'STRING' },
  { name: 'Circuit Owner', type: 'STRING' },
  { name: 'ProductDescription', type: 'STRING' },
  { name: 'SR Status', type: 'STRING' }
  ];
}

function normalizeRowLength(row, expected) {
  var out = row.slice(0, expected);
  while (out.length < expected) out.push('');
  return out;
}

function csvFromRows(rows) {
  // Minimal quoting: wrap fields containing comma, quote, or newline
  return rows.map(function(r){
    return r.map(function(f){
      if (f == null) return '';
      f = String(f);
      if (/[",\n\r]/.test(f)) {
        return '"' + f.replace(/"/g, '""') + '"';
      }
      return f;
    }).join(',');
  }).join('\n');
}

function loadAttachmentToTemp(attachment, tempTableId, isFirst) {
  var csvData = Utilities.parseCsv(attachment.getDataAsString());
  if (!csvData || csvData.length === 0) return 0;
  // remove header row if present
  var header = csvData[0];
  var looksLikeHeader = header && header.length >= 3 && /CustID|SRNo|Product/i.test(header.join(','));
  if (looksLikeHeader) csvData.shift();
  var filtered = csvData.filter(function(row){ return row && row.some(function(c){ return c !== ''; }); });
  var rows = filtered.map(function(row){
    var norm = normalizeRowLength(row, 9);
    return [
      norm[0],  // CustID
      norm[1],  // CustName
      norm[2],  // SRNo
      norm[3],  // Product Family
      norm[4],  // Product ID
      norm[5],  // Insight Circuit ID
      norm[6],  // Circuit Owner
      norm[7],  // ProductDescription
      norm[8]   // SR Status
    ];
  });
  if (rows.length === 0) return 0;

  var content = csvFromRows(rows);
  var job = {
    configuration: {
      load: {
        destinationTable: {
          projectId: projectId,
          datasetId: datasetId,
          tableId: tempTableId
        },
        sourceFormat: 'CSV',
        skipLeadingRows: 0,
        writeDisposition: isFirst ? 'WRITE_TRUNCATE' : 'WRITE_APPEND',
        createDisposition: 'CREATE_IF_NEEDED',
        allowQuotedNewlines: true,
        fieldDelimiter: ',',
        quote: '"',
        encoding: 'UTF-8',
        schema: { fields: getSchemaFields() }
      }
    }
  };
  var jobResp = BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(content));
  var jobId = jobResp && jobResp.jobReference ? jobResp.jobReference.jobId : null;
  if (VERBOSE) console.log('      BigQuery load submitted: table=', datasetId + '.' + tempTableId, 'writeDisposition=', (isFirst ? 'WRITE_TRUNCATE' : 'WRITE_APPEND'), 'jobId=', jobId);
  return { rows: rows.length, jobId: jobId };
}

function runMergeTempIntoTarget(tempTableId) {
  var fqTemp = '`' + projectId + '.' + datasetId + '.' + tempTableId + '`';
  var fqTarget = '`' + projectId + '.' + datasetId + '.' + tableId + '`';
  var query = [
    'MERGE ' + fqTarget + ' T',
    'USING (',
    '  SELECT * FROM (',
    '    SELECT',
  '      CAST(CustID AS STRING) AS CustID,',
  '      CAST(CustName AS STRING) AS CustName,',
  '      CAST(SRNo AS STRING) AS SRNo,',
  '      CAST(`Product Family` AS STRING) AS `Product Family`,',
  '      CAST(`Product ID` AS STRING) AS `Product ID`,',
  '      CAST(`Insight Circuit ID` AS STRING) AS `Insight Circuit ID`,',
  '      CAST(`Circuit Owner` AS STRING) AS `Circuit Owner`,',
  '      CAST(ProductDescription AS STRING) AS ProductDescription,',
  '      CAST(`SR Status` AS STRING) AS `SR Status`,',
  '      ROW_NUMBER() OVER (PARTITION BY SRNo ORDER BY SRNo) AS rn',
    '    FROM ' + fqTemp,
    '    WHERE SRNo IS NOT NULL AND SRNo != ""',
    '  ) WHERE rn = 1',
    ') S',
    'ON T.SRNo = S.SRNo',
    'WHEN MATCHED THEN UPDATE SET',
    '  T.CustID = S.CustID,',
    '  T.CustName = S.CustName,',
    '  T.`Product Family` = S.`Product Family`,',
  '  T.`Product ID` = S.`Product ID`,',
  '  T.`Insight Circuit ID` = S.`Insight Circuit ID`,',
  '  T.`Circuit Owner` = S.`Circuit Owner`,',
  '  T.ProductDescription = S.ProductDescription,',
  '  T.`SR Status` = S.`SR Status`',
    'WHEN NOT MATCHED THEN',
  '  INSERT (SRNo, CustID, CustName, `Product Family`, `Product ID`, `Insight Circuit ID`, `Circuit Owner`, ProductDescription, `SR Status`)',
  '  VALUES (S.SRNo, S.CustID, S.CustName, S.`Product Family`, S.`Product ID`, S.`Insight Circuit ID`, S.`Circuit Owner`, S.ProductDescription, S.`SR Status` )'
  ].join('\n');

  var request = {
    query: query,
    useLegacySql: false
  };
  var response = BigQuery.Jobs.query(request, projectId);
  if (VERBOSE && response && response.jobReference) {
    console.log('MERGE jobId=', response.jobReference.jobId);
  }
  if (!response.jobComplete) {
    throw new Error('Merge job did not complete in time');
  }
  if (response.status && response.status.errorResult) {
    throw new Error('Merge error: ' + JSON.stringify(response.status.errors || response.status.errorResult));
  }
}

function dropTempTable(tempTableId) {
  var fqTemp = projectId + ':' + datasetId + '.' + tempTableId;
  try {
    BigQuery.Tables.remove(projectId, datasetId, tempTableId);
    console.log('Dropped temp table ' + fqTemp);
  } catch (e) {
    console.warn('Failed to drop temp table ' + fqTemp + ': ' + e.message);
  }
}

// Minimal wait util for BigQuery query jobs (used by logPipelineRun)
function waitForJobCompletion(job) {
  try {
    var jobId = job.jobReference && job.jobReference.jobId ? job.jobReference.jobId : null;
    if (!jobId) return; // nothing to wait for
    var attempts = 0;
    var maxAttempts = 30;
    while (attempts < maxAttempts) {
      Utilities.sleep(2000);
      job = BigQuery.Jobs.get(projectId, jobId);
      if (job.status && job.status.state === 'DONE') break;
      attempts++;
    }
  } catch (e) {
    console.warn('waitForJobCompletion failed: ' + e.message);
  }
}