// Best practice: Use strict mode to catch common coding errors.
'use strict';

/**
 * @fileoverview This script automates the process of loading HubSpot survey data from
 * Excel files stored in Google Drive into Google BigQuery. It is designed to be
 * "intelligent and seamless," automatically picking up the latest monthly files,
 * staging them in BigQuery, and using a MERGE operation to prevent duplicates.
 */

/**
 * The ID of the Google Drive folder where the monthly HubSpot survey Excel files are stored.
 * @type {string}
 */
const DRIVE_FOLDER_ID = '1ZgMpFUqoPH2WfshpGMRBSmrRrfzf8Cij';

/**
 * The Google Cloud Project ID.
 * @type {string}
 */
const PROJECT_ID = 'pccw-internal-virt-agent-uat';

/**
 * Configuration object for the different HubSpot survey types.
 * Each configuration specifies the BQ dataset, table name, file name pattern,
 * unique record identifier, and the schema mapping.
 */
const SURVEY_CONFIGS = {
  REMEDY_CLOSURE: {
    datasetId: 'GSO',
    tableName: 'HubspotRemedyClosureSurvey',
    file_pattern: /hubspot-core-report-remedy-ticket-closure-survey-fe-\d{4}-\d{2}-\d{2}\.xlsx/,
    record_id: 'record_id',
    schema: {
      'Record ID': 'record_id',
      'Date': 'submission_timestamp',
      'Survey Name': 'survey_name',
      'srno': 'srno',
      'incid': 'incid',
      'Email': 'email',
      'Company Name': 'company_name',
      'I am satisfied with the resolution of my issue or request.': 'satisfaction_resolution',
      'The Support Team provided clear and helpful communication.': 'support_team_communication',
      'It was easy to get my issue or request resolved.': 'ease_of_resolution',
      'What could we have done better?': 'improvement_feedback',
      'Survey ID': 'survey_id',
      'Ingestion id': 'ingestion_id',
      'Survey Type': 'survey_type',
    },
  },
  SCN_FEEDBACK: {
    datasetId: 'GSO',
    tableName: 'HubspotSCNFeedback',
    file_pattern: /hubspot-core-report-scn-feedback-submissions-report-\d{4}-\d{2}-\d{2}\.xlsx/,
    record_id: 'record_id',
    schema: {
      'Record ID': 'record_id',
      'Date': 'submission_timestamp',
      'Survey Name': 'survey_name',
      'srno': 'srno',
      'Email': 'email',
      'Company Name': 'company_name',
      'How organized and efficient was our account team in managing the solution design-to-quote-to-order process?': 'account_team_process_rating',
      'Please rate the overall interpersonal skills of the project manager, including their professionalism, availability, responsiveness, knowledge base, and communication abilities.': 'project_manager_interpersonal_rating',
      'Please assess the project planning, monitoring, and control (PMC) process. Consider the effectiveness of the kick-off email/meeting, adequacy of the project plan or schedule, frequency and accuracy of progress updates, timeliness of milestone achievement, and risk management strategies.': 'pmc_process_rating',
      'Please rate your overall satisfaction with the project implementation process, including site visit arrangements, pre-wiring coordination, equipment installation planning, configuration management, and turn-up execution.': 'implementation_process_rating',
      'Please evaluate the project handover process, specifically the user acceptance test (UAT) arrangements, handover documentation, and the overall handover process.': 'handover_process_rating',
      'Please rate your satisfaction with the overall performance of project delivery and implementation.': 'overall_delivery_rating',
      'How likely are you to recommend our products and services to others?': 'recommendation_likelihood',
      'Survey ID': 'survey_id',
      'Ingestion id': 'ingestion_id',
      'Survey Type': 'survey_type',
    },
  },
};

/**
 * Main function to orchestrate the loading process for all configured surveys.
 * This is the primary entry point to be triggered.
 */
function loadHubspotSurveys() {
  for (const key in SURVEY_CONFIGS) {
    const config = SURVEY_CONFIGS[key];
    console.log(`Processing survey type: ${key}`);
    try {
      processSingleSurvey(config);
      console.log(`Successfully processed survey type: ${key}`);
    } catch (e) {
      console.error(`Failed to process survey type: ${key}. Error: ${e.toString()}`);
      // Continue to the next survey even if one fails.
    }
  }
}

/**
 * Processes a single survey type based on its configuration.
 * @param {object} config The configuration object for a specific survey.
 */
function processSingleSurvey(config) {
  const folder = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  const latestFile = findLatestFile(folder, config.file_pattern);

  if (!latestFile) {
    console.log(`No matching file found for pattern: ${config.file_pattern}. Skipping.`);
    return;
  }

  console.log(`Latest file found: ${latestFile.getName()}`);

  const tempSheet = convertExcelToGoogleSheet(latestFile);
  const sheetData = readDataFromSheet(tempSheet.getSheets()[0], config.schema);
  
  if (sheetData.length === 0) {
    console.log('No data found in the sheet. Cleaning up and skipping.');
    DriveApp.getFileById(tempSheet.getId()).setTrashed(true);
    return;
  }

  const stagingTableId = `${config.tableName}_staging_${new Date().getTime()}`;
  const stagingTable = createStagingTable(config.datasetId, stagingTableId, sheetData[0]);

  try {
    loadDataToStaging(sheetData, config.datasetId, stagingTableId);
    runMergeJob(config.datasetId, config.tableName, stagingTableId, config.record_id);
    console.log('Merge job completed successfully.');
  } finally {
    // Ensure cleanup happens even if the merge job fails.
    deleteBigQueryTable(config.datasetId, stagingTableId);
    DriveApp.getFileById(tempSheet.getId()).setTrashed(true);
    console.log('Cleaned up temporary Google Sheet and BigQuery staging table.');
  }
}

/**
 * Finds the most recently updated file in a folder that matches a regex pattern.
 * @param {GoogleAppsScript.Drive.Folder} folder The Drive folder to search in.
 * @param {RegExp} filePattern The regex pattern to match file names against.
 * @return {GoogleAppsScript.Drive.File | null} The most recent file, or null if none found.
 */
function findLatestFile(folder, filePattern) {
  const files = folder.getFiles();
  let latestFile = null;
  let latestDate = new Date(0);

  while (files.hasNext()) {
    const file = files.next();
    if (filePattern.test(file.getName())) {
      const lastUpdated = file.getLastUpdated();
      if (lastUpdated > latestDate) {
        latestDate = lastUpdated;
        latestFile = file;
      }
    }
  }
  return latestFile;
}

/**
 * Converts an Excel file (.xlsx) to a temporary Google Sheet.
 * @param {GoogleAppsScript.Drive.File} excelFile The source Excel file.
 * @return {GoogleAppsScript.Spreadsheet.Spreadsheet} The newly created Google Sheet.
 */
function convertExcelToGoogleSheet(excelFile) {
  const tempSheet = Drive.Files.create(
    { title: `[TEMP] ${excelFile.getName()}`, parents: [{ id: DRIVE_FOLDER_ID }] },
    excelFile.getBlob(),
    { convert: true }
  );
  return SpreadsheetApp.openById(tempSheet.id);
}

/**
 * Reads data from a sheet, mapping headers to BigQuery column names.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet The sheet to read from.
 * @param {object} schema The schema mapping from sheet headers to BQ columns.
 * @return {Array<object>} An array of row objects with BQ column names as keys.
 */
function readDataFromSheet(sheet, schema) {
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) return [];

  const headers = data[0];
  const bqHeaders = headers.map(header => schema[header.trim()] || null);

  return data.slice(1).map(row => {
    const rowObject = {};
    bqHeaders.forEach((bqHeader, index) => {
      if (!bqHeader) return;
      const value = row[index];
      // Always include the field so the staging schema is complete, even for blank values.
      if (value === '') {
        rowObject[bqHeader] = null;
      } else if (bqHeader.toLowerCase().includes('timestamp') && value instanceof Date) {
        // Handle date conversion if necessary
        rowObject[bqHeader] = Utilities.formatDate(value, Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss'Z'");
      } else {
        rowObject[bqHeader] = value;
      }
    });
    return rowObject;
  });
}

/**
 * Creates a temporary staging table in BigQuery.
 * @param {string} datasetId The BigQuery dataset ID.
 * @param {string} tableId The ID for the new staging table.
 * @param {object} sampleRow A sample row object to infer the schema.
 * @return {GoogleAppsScript.BigQuery.Schema.Table} The created table resource.
 */
function createStagingTable(datasetId, tableId, sampleRow) {
  const fields = Object.keys(sampleRow).map(key => {
    let type = 'STRING';
    if (typeof sampleRow[key] === 'number') {
      type = Number.isInteger(sampleRow[key]) ? 'INTEGER' : 'NUMERIC';
    } else if (key.toLowerCase().includes('timestamp')) {
      type = 'TIMESTAMP';
    }
    return { name: key, type: type };
  });

  const table = BigQuery.Tables.insert(
    {
      tableReference: {
        projectId: PROJECT_ID,
        datasetId: datasetId,
        tableId: tableId,
      },
      schema: { fields: fields },
      // Expire the staging table after 1 hour automatically as a failsafe
      expirationTime: (new Date().getTime() + 60 * 60 * 1000).toString()
    },
    PROJECT_ID,
    datasetId
  );
  console.log(`Created staging table: ${tableId}`);
  return table;
}

/**
 * Loads data into the BigQuery staging table.
 * @param {Array<object>} data The array of row objects to load.
 * @param {string} datasetId The BigQuery dataset ID.
 * @param {string} tableId The staging table ID.
 */
function loadDataToStaging(data, datasetId, tableId) {
  const dataAsNdJson = data.map(row => JSON.stringify(row)).join('\n');
  const blob = Utilities.newBlob(dataAsNdJson, 'application/octet-stream');

  const job = BigQuery.Jobs.insert(
    {
      configuration: {
        load: {
          destinationTable: {
            projectId: PROJECT_ID,
            datasetId: datasetId,
            tableId: tableId,
          },
          sourceFormat: 'NEWLINE_DELIMITED_JSON',
        },
      },
    },
    PROJECT_ID,
    blob
  );
  console.log(`Load job started. Job ID: ${job.jobReference.jobId}`);
  waitForJob(job.jobReference.jobId);
}

/**
 * Runs the MERGE job to upsert data from staging to the final table.
 * @param {string} datasetId The BigQuery dataset ID.
 * @param {string} tableName The final destination table ID.
 * @param {string} stagingTableId The source staging table ID.
 * @param {string} recordIdColumn The column name of the unique record identifier.
 */
function runMergeJob(datasetId, tableName, stagingTableId, recordIdColumn) {
  const targetTable = `${PROJECT_ID}.${datasetId}.${tableName}`;
  const sourceTable = `${PROJECT_ID}.${datasetId}.${stagingTableId}`;

  // Get columns from the STAGING table to ensure we only merge what was loaded
  const bqColumns = BigQuery.Tables.get(PROJECT_ID, datasetId, stagingTableId).schema.fields.map(f => f.name);
  
  const setClause = bqColumns
    .filter(col => col !== recordIdColumn)
    .map(col => `T.${col} = S.${col}`)
    .join(', ');
    
  const insertColumns = bqColumns.join(', ');
  const sourceColumns = bqColumns.map(col => `S.${col}`).join(', ');

  // If there are no columns to update (only the record_id), the MERGE is pointless.
  if (setClause.trim() === '') {
    console.log(`Skipping MERGE for ${stagingTableId} as no matching columns to update were found in the staged data.`);
    return;
  }

  const mergeSql = `
    MERGE ${targetTable} AS T
    USING ${sourceTable} AS S
    ON T.${recordIdColumn} = S.${recordIdColumn}
    WHEN MATCHED THEN
      UPDATE SET ${setClause}
    WHEN NOT MATCHED THEN
      INSERT (${insertColumns}) VALUES (${sourceColumns})
  `;

  console.log('Executing MERGE SQL:', mergeSql);

  const job = BigQuery.Jobs.insert(
    {
      configuration: {
        query: {
          query: mergeSql,
          useLegacySql: false,
        },
      },
    },
    PROJECT_ID
  );
  console.log(`Merge job started. Job ID: ${job.jobReference.jobId}`);
  waitForJob(job.jobReference.jobId);
}

/**
 * Deletes a BigQuery table.
 * @param {string} datasetId The BigQuery dataset ID.
 * @param {string} tableId The ID of the table to delete.
 */
function deleteBigQueryTable(datasetId, tableId) {
  try {
    BigQuery.Tables.remove(PROJECT_ID, datasetId, tableId);
    console.log(`Successfully deleted table: ${tableId}`);
  } catch (e) {
    console.error(`Could not delete table ${tableId}. Please remove it manually. Error: ${e}`);
  }
}

/**
 * Waits for a BigQuery job to complete.
 * @param {string} jobId The ID of the job to wait for.
 */
function waitForJob(jobId) {
  let sleepTimeMs = 500;
  while (true) {
    const job = BigQuery.Jobs.get(PROJECT_ID, jobId);
    if (job.status.state === 'DONE') {
      if (job.status.errorResult) {
        throw new Error(`Job failed: ${JSON.stringify(job.status.errors)}`);
      }
      console.log(`Job ${jobId} completed.`);
      return;
    }
    Utilities.sleep(sleepTimeMs);
    // Exponential backoff
    sleepTimeMs *= 1.5;
  }
}

/**
 * Helper function to create a monthly trigger for the main `loadHubspotSurveys` function.
 * This function is intended to be run manually once from the script editor to set up automation.
 */
function createMonthlyTrigger() {
  // Check if a trigger already exists to avoid duplicates
  const existingTriggers = ScriptApp.getProjectTriggers();
  const triggerExists = existingTriggers.some(
    trigger => trigger.getHandlerFunction() === 'loadHubspotSurveys'
  );

  if (triggerExists) {
    console.log('A monthly trigger for loadHubspotSurveys already exists.');
    return;
  }
  
  // Creates a trigger that runs the first day of every month at ~2-3 AM.
  ScriptApp.newTrigger('loadHubspotSurveys')
    .timeBased()
    .onMonthDay(1)
    .atHour(2)
    .create();
    
  console.log('Successfully created a monthly trigger for loadHubspotSurveys.');
}
