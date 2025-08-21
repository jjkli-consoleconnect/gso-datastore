// =================================================
// ENABLE BIGQUERY API in Advanced Google Services
// (Extensions → Advanced Google services → BigQuery API ON
//  then enable in Cloud Console.)
// =================================================

// === CONFIGURATION ===
// List the Drive file IDs pointing to your JSONL log files
var FILE_IDS = [
  '1mVCzizY_JCT6HJsH1QpzMWH9sjMR2rQ8',
  // Add more file IDs here as needed
];

// Your GCP project, BigQuery dataset and table
var PROJECT_ID = 'pccw-internal-virt-agent-uat';
var DATASET_ID = 'GSO';
var TABLE_ID   = 'PipelineRuns';
var SCRIPT_PIPELINE_NAME = 'GAS_LogsToBQ';
var CURRENT_RUN_ID = null;


/**
 * Writes a small “heartbeat” row into your BigQuery log table.
 */
function logScriptEvent(step, status, message) {
  if (!CURRENT_RUN_ID) CURRENT_RUN_ID = Utilities.getUuid();
  logPipelineRun(SCRIPT_PIPELINE_NAME, CURRENT_RUN_ID, status === 'ERROR' ? 'ERROR' : 'INFO', status, step + ': ' + message, null, null, null, null, null);
}

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
    var query = "\n      MERGE `" + PROJECT_ID + "." + DATASET_ID + "." + TABLE_ID + "` T\n      USING (SELECT '" + pname + "' AS PipelineName, '" + rid + "' AS RunID) S\n      ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID\n      WHEN MATCHED THEN UPDATE SET\n        RunTime = CURRENT_TIMESTAMP(),\n        WindowStart = " + wsExpr + ",\n        WindowEnd = " + weExpr + ",\n        RowsMerged = " + rmExpr + ",\n        LogLevel = '" + lvl + "',\n        Message = '" + msg + "',\n        Status = '" + stat + "',\n        ErrorCode = " + ecExpr + ",\n        Context = CAST(NULL AS JSON)\n      WHEN NOT MATCHED THEN\n        INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, Context)\n        VALUES (CURRENT_TIMESTAMP(), '" + pname + "', " + wsExpr + ", " + weExpr + ", " + rmExpr + ", '" + lvl + "', '" + msg + "', '" + rid + "', '" + stat + "', " + ecExpr + ", CAST(NULL AS JSON));\n    ";
    var job = BigQuery.Jobs.insert({ configuration: { query: { query: query, useLegacySql: false } } }, PROJECT_ID);
    waitForJobCompletion(job.jobReference.jobId);
  } catch (e) { console.warn('logPipelineRun failed: ' + e.message); }
}

function escapeSqlLiteral(s) { return s.replace(/'/g, "''"); }


/**
 * Imports one JSONL file from Drive into BigQuery.
 * 1) Loads into a temp table
 * 2) MERGEs into the target table (dedupe on BatchID+Timestamp+RunID)
 * 3) Drops the temp table
 */
function importLogToBigQuery_v2(fileId) {
  var batchID     = Utilities.getUuid();
  var tempTableId = TABLE_ID + '_temp_' + batchID.replace(/-/g, '');

  try {
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Starting batch ${batchID}`);

    // Fetch file blob
    var file = DriveApp.getFileById(fileId);
    logScriptEvent('importLogToBigQuery_v2', 'INFO', 
      `Got file: ${file.getName()} (${file.getSize()} bytes)`);

    var jsonDataBlob = file.getBlob();

    // 1) Load JSONL into temp table
    var loadJob = {
      configuration: {
        load: {
          destinationTable: {
            projectId: PROJECT_ID,
            datasetId: DATASET_ID,
            tableId:    tempTableId
          },
          sourceFormat:    'NEWLINE_DELIMITED_JSON',
          writeDisposition:'WRITE_TRUNCATE',
          autodetect:      true
        }
      }
    };
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Loading into temp table ${tempTableId}`);
    var job = BigQuery.Jobs.insert(loadJob, PROJECT_ID, jsonDataBlob);
    waitForJobCompletion(job.jobReference.jobId);
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Loaded data into ${tempTableId}`);

    // 2) MERGE into PipelineRuns (map legacy columns to new schema)
    var mergeQuery = `
      MERGE \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` T
      USING \`${PROJECT_ID}.${DATASET_ID}.${tempTableId}\` S
      ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID
      WHEN MATCHED THEN UPDATE SET
        RunTime = CURRENT_TIMESTAMP(),
        LogLevel = S.LogLevel,
        Message = S.Message,
        Status = CASE
          WHEN UPPER(S.LogLevel) IN ('ERROR','FAIL') THEN 'ERROR'
          WHEN UPPER(S.LogLevel) = 'SUCCESS' THEN 'SUCCESS'
          ELSE 'INFO'
        END,
        Context = CAST(TO_JSON_STRING(STRUCT(S.FunctionName AS FunctionName, S.BatchID AS BatchID, S.Details AS Details)) AS JSON)
      WHEN NOT MATCHED THEN
        INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, Context)
        VALUES (
          CURRENT_TIMESTAMP(),
          S.PipelineName,
          NULL,
          NULL,
          NULL,
          S.LogLevel,
          S.Message,
          S.RunID,
          CASE
            WHEN UPPER(S.LogLevel) IN ('ERROR','FAIL') THEN 'ERROR'
            WHEN UPPER(S.LogLevel) = 'SUCCESS' THEN 'SUCCESS'
            ELSE 'INFO'
          END,
          NULL,
          CAST(TO_JSON_STRING(STRUCT(S.FunctionName AS FunctionName, S.BatchID AS BatchID, S.Details AS Details)) AS JSON)
        )
    `;
    var mergeJob = {
      configuration: {
        query: {
          query:     mergeQuery,
          useLegacySql: false
        }
      }
    };
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Merging ${tempTableId} → ${TABLE_ID}`);
    var mergeResult = BigQuery.Jobs.insert(mergeJob, PROJECT_ID);
    waitForJobCompletion(mergeResult.jobReference.jobId);
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Merged into ${TABLE_ID}`);

    // 3) Drop the temp table
    var dropQuery = `DROP TABLE \`${PROJECT_ID}.${DATASET_ID}.${tempTableId}\``;
    var dropJob = {
      configuration: {
        query: {
          query:        dropQuery,
          useLegacySql: false
        }
      }
    };
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Dropping temp table ${tempTableId}`);
    var dropResult = BigQuery.Jobs.insert(dropJob, PROJECT_ID);
    waitForJobCompletion(dropResult.jobReference.jobId);
    logScriptEvent('importLogToBigQuery_v2', 'INFO', `Dropped temp table ${tempTableId}`);

    logScriptEvent('importLogToBigQuery_v2', 'SUCCESS', `Completed batch ${batchID}`);
  }
  catch (e) {
    logScriptEvent('importLogToBigQuery_v2', 'ERROR', e.message);
    throw e;
  }
}


/**
 * Polls a BigQuery job until it’s DONE or errors/timeouts.
 */
function waitForJobCompletion(jobId) {
  var maxAttempts = 60;
  var attempts    = 0;
  
  while (attempts < maxAttempts) {
    Utilities.sleep(5000);
    var status = BigQuery.Jobs.get(PROJECT_ID, jobId).status;
    if (status.state === 'DONE') {
      if (status.errorResult) {
        throw new Error('BigQuery job failed: ' + status.errorResult.message);
      }
      return;
    }
    attempts++;
  }
  throw new Error(`BigQuery job ${jobId} timed out after ${maxAttempts * 5} seconds.`);
}


/**
 * Main entrypoint: loops through FILE_IDS and imports each.
 */
function importAllLogsToBigQuery() {
  Logger.log('=== importAllLogsToBigQuery START ===');
  logScriptEvent('importAllLogsToBigQuery', 'INFO', 'Begin full import');

  FILE_IDS.forEach(function(fileId, idx) {
    Logger.log(`Processing file ${idx+1}/${FILE_IDS.length}: ${fileId}`);
    logScriptEvent('importAllLogsToBigQuery', 'INFO', `Importing file ${fileId}`);
    try {
      importLogToBigQuery_v2(fileId);
      Logger.log(`✅ Success importing ${fileId}`);
    } catch (e) {
      Logger.log(`❌ ERROR importing ${fileId}: ${e.message}`);
      logScriptEvent('importAllLogsToBigQuery', 'ERROR', `Failed file ${fileId}: ${e.message}`);
    }
  });

  logScriptEvent('importAllLogsToBigQuery', 'INFO', 'Completed full import');
  Logger.log('=== importAllLogsToBigQuery END ===');
}