// --- GLOBAL VARIABLES ---
var scriptName = "DriveToBQ - HDWL";
var projectId = "pccw-internal-virt-agent-uat";
var folderId = "1-CN9TVdXLQlG033djKVG5slzbhADbpdA"; // Assuming this is for temporary JSON files on Drive
var errorNotificationEmails = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com";

// --- NEW DRIVE FOLDER IDs ---
var sourceDriveFolderId = "15aWB6BmkjbySqHb5NWkaOn6fMQIZ5an0";
var archiveDriveFolderId = "16RazUSdV7klL8ZAqNqVNUx7mWtpKkZi-";

// Centralized PipelineRuns logging config
var pipelineRunsDatasetId = 'GSO';
var pipelineRunsTableId = 'PipelineRuns';
var currentRunId = null; // set in main()
var scriptStartTime = null; // set in main()


// --- CONFIGURATIONS FOR EACH CSV TYPE ---
const csvTypeConfigurations = [
  {
    name: "HelpDeskAllNOC",
    filenamePrefix: "helpdesk", // Matches "HelpDesk 06-18-2025 3-23-9"
    stagingDatasetId: "Staging",
    stagingTableId: "HelpDeskAllNOC",
    targetDatasetId: "GSO",
    targetTableId: "HelpDeskAllNOC",
    allColumns: [ // Ensure these map exactly to BigQuery schema for testhd
      "Incident_Number", "Status", "CaseType", "Assigned_Group", "Categorization_Tier_1",
      "Categorization_Tier_2", "Categorization_Tier_3", "GCSC_1st_Customer_Update",
      "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update", "Initial_Response_Time",
      "Second_Response_Time", "Third_Response_Time", "Prod_ID", "Fault_Cause",
      "Closed_Date", "Submit_Date", "Assignee", "Closed_By", "Submitter", "TrueMTTR_mins",
      "Cust_ID", "Carrier", "Customer_Name", "SRno", "LastResolvedDate", "ReportedDate",
      "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy",
      "Product_Family", "ProductDescription", "GSMP_Circuit_ID" // <-- Added new field
    ],
    primaryKeyForMerge: "Incident_Number", // Incident_Number is the primary key for HD
    fieldMap: { // Header mapping for HelpDesk CSV
      "IncidentNumber": "Incident_Number", "casetype": "CaseType", "Assigned Group": "Assigned_Group",
      "Categorization Tier 1": "Categorization_Tier_1", "Categorization Tier 2": "Categorization_Tier_2",
      "Categorization Tier 3": "Categorization_Tier_3", "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
      "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update", "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
      "Initial Response Time": "Initial_Response_Time", "Second Response Time": "Second_Response_Time",
      "Third Response Time": "Third_Response_Time", "Prod ID": "Prod_ID", "FaultCause": "Fault_Cause",
      "Closed Date": "Closed_Date", "Submit Date": "Submit_Date", "ClosedBy": "Closed_By",
      "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRno": "SRno", "ReportedBy": "ReportedBy",
      "Product Family": "Product_Family", // <-- Add mapping
      "ProductDescription": "ProductDescription", // <-- Add mapping
      "GSMP Circuit ID": "GSMP_Circuit_ID" // <-- Added new mapping
    },
    // Timestamp and Integer fields for HelpDesk
    timestampFields: ["GCSC_1st_Customer_Update", "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update",
                      "Closed_Date", "Submit_Date", "LastResolvedDate", "ReportedDate", "RespondedDate",
                      "LastModifiedDate"],
    integerFields: ["Initial_Response_Time", "Second_Response_Time", "Third_Response_Time", "TrueMTTR_mins"]
  },
  {
    name: "WorkLog",
    filenamePrefix: "worklog", // Matches "WorkLog 06-18-2025 3-23-9"
    stagingDatasetId: "Staging",
    stagingTableId: "WorkLogAllNOC", // BigQuery staging table for Worklog
    targetDatasetId: "GSO",
    targetTableId: "WorkLogAllNOC", // BigQuery target table for Worklog
    allColumns: [ // Ensure these map exactly to BigQuery schema for testwl
      "Incident_Number", "WorkLog_Type", "WorkLog_ID", "WorkLog_Submit_Date",
      "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By", "ExtractedDescription" // <-- Added new field
    ],
    primaryKeyForMerge: "WorkLog_ID", // WorkLog_ID is the primary key for WL
    fieldMap: { // Header mapping for Worklog CSV
      "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
      "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
      "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
      "LastModifiedBy": "Last_Modified_By",
      "ExtractedDescription": "ExtractedDescription" // <-- Added new mapping
    },
    // Timestamp and Integer fields for WorkLog
    timestampFields: ["WorkLog_Submit_Date", "Last_Modified_Date"],
    integerFields: [] // No integer fields in WorkLog CSV provided
  }
];

// --- FUNCTIONS ---

/**
 * Main function to iterate through files in the source Google Drive folder,
 * process CSVs, and trigger BigQuery loads.
 */
function processDriveFiles() {
  console.log(`Starting data pipeline run from Google Drive folder: ${sourceDriveFolderId}`);
  if (!currentRunId) {
    currentRunId = Utilities.getUuid();
    scriptStartTime = new Date();
    logPipelineRun(scriptName, currentRunId, 'RUNNING', 'INFO', 'Pipeline run started', null, null, null, null, null);
  }

  let sourceFolder;
  let archiveFolder;

  try {
    sourceFolder = DriveApp.getFolderById(sourceDriveFolderId);
    archiveFolder = DriveApp.getFolderById(archiveDriveFolderId);
  } catch (e) {
    const errorMessage = `Error accessing Drive folders: ${e.message}. Please check folder IDs and permissions.`;
    console.error(errorMessage);
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: `CRITICAL ERROR in ${scriptName}: Drive Folder Access Failed`,
      body: errorMessage + `\n\nStack trace:\n${e.stack}`
    });
    return; // Exit immediately if folders can't be accessed
  }

  const files = sourceFolder.getFiles();
  let totalFilesFound = 0;
  let totalFilesProcessedSuccessfully = 0;
  let totalFilesArchivedSuccessfully = 0;
  let totalCSVsLoadedToBigQuery = 0; // Number of successful BigQuery loads for CSVs
  let totalRowsMerged = 0;
  let anyProcessingIssueEncountered = false; // Flag for any non-critical failure that warrants a warning email

  // Convert iterator to array for easier handling and length check if needed
  const fileList = [];
  while (files.hasNext()) {
    fileList.push(files.next());
  }
  totalFilesFound = fileList.length;

  console.log(`Found ${totalFilesFound} files in the source folder.`);

  if (totalFilesFound === 0) {
    console.log("No new files found for processing. Exiting.");
  // Finalize run with success and 0 rows
  logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'No files to process', null, null, 0, null, null);
    return;
  }

  // Sort files by last updated date if desired (oldest first for processing)
  fileList.sort((a, b) => a.getLastUpdated().getTime() - b.getLastUpdated().getTime());

  for (const file of fileList) {
    const fileName = file.getName();
    console.log(`\n--- Processing File: "${fileName}" (ID: ${file.getId()}) ---`);

    if (!fileName.toLowerCase().endsWith(".csv")) {
      console.log(`  Skipping non-CSV file: "${fileName}"`);
      // Optionally move non-CSV files to archive or a "skipped" folder if they shouldn't remain in source
      continue;
    }

    // Attempt to process the CSV file
    const processStatus = processCsvFile(file); // This new function replaces processAttachmentByType logic

    if (processStatus && processStatus.success === true) {
      totalFilesProcessedSuccessfully++;
      totalCSVsLoadedToBigQuery++; // Increment if BigQuery load/merge was successful for this CSV
      totalRowsMerged += (processStatus.rowsMerged || 0);

      try {
        file.moveTo(archiveFolder);
        console.log(`  Successfully processed and archived file: "${fileName}"`);
        totalFilesArchivedSuccessfully++;
      } catch (e) {
        console.error(`  Error archiving file "${fileName}" (ID: ${file.getId()}): ${e.message}`);
        anyProcessingIssueEncountered = true;
        // File processed but not archived, will remain in source. Warning email will be sent.
      }
    } else if (processStatus === false) {
      console.warn(`  Failure to process file: "${fileName}". It remains in the source folder.`);
      anyProcessingIssueEncountered = true;
    } else { // processStatus is null (unrecognized CSV type)
      console.warn(`  CSV file "${fileName}" does not match any known configuration (HelpDesk/WorkLog). It remains in the source folder.`);
      anyProcessingIssueEncountered = true; // Unrecognized CSV is still an issue
    }
  } // End of file loop

  console.log("\n--- Overall Processing Summary ---");
  console.log(`Total files found in source folder: ${totalFilesFound}`);
  console.log(`Total CSVs processed and loaded to BigQuery: ${totalCSVsLoadedToBigQuery}`);
  console.log(`Total rows merged into BigQuery: ${totalRowsMerged}`);
  console.log(`Total files successfully archived: ${totalFilesArchivedSuccessfully}`);

  if (anyProcessingIssueEncountered || totalFilesArchivedSuccessfully < totalFilesProcessedSuccessfully) {
    const warningBody = `Some files were not fully processed or archived from ${sourceDriveFolderId}.
    \nPlease check Google Apps Script logs for "${scriptName}" for details.`;
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: `WARNING in ${scriptName}: Processing Issues Detected in Drive Files`,
      body: warningBody
    });
    console.warn("A warning email has been sent due to partial or failed processing.");
  } else {
    console.log("All matching pending files processed successfully. No warning email sent.");
  }
  console.log("Pipeline finished");
  // SUCCESS log with rows merged = actual BigQuery row count
  logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'Pipeline finished', null, null, totalRowsMerged, null, null);
}

/**
 * Dispatches a CSV file for processing based on its filename prefix.
 * This function replaces the original processAttachmentByType but takes a Drive File.
 * @param {DriveApp.File} file The Google Drive file to process.
 * @returns {boolean|null} True if successfully processed, False if processing failed, Null if unrecognized CSV type.
 */
function processCsvFile(file) {
  const fileNameLower = file.getName().toLowerCase();

  for (const config of csvTypeConfigurations) {
    if (fileNameLower.startsWith(config.filenamePrefix) && fileNameLower.endsWith(".csv")) {
      console.log(`  Identified "${config.name}" CSV: "${file.getName()}"`);
      try {
        // Generic JSON conversion applies custom field mapping and type handling
        const jsonFileId = processFileToJsonGeneric(file, config); // Pass Drive File
        if (jsonFileId) {
          // Generic BigQuery load to staging
          loadJsonToBigQueryGeneric(jsonFileId, config);
          // Generic BigQuery merge to target
          const rowsMerged = mergeTablesInBigQueryGeneric(config);
          console.log(`  Successfully processed and loaded "${config.name}" data. Rows merged: ${rowsMerged}`);
          return { success: true, rowsMerged: rowsMerged }; // Successfully handled this attachment
        } else {
          console.error(`  JSON conversion resulted in null for: ${file.getName()}`);
          return false; // Conversion failed (e.g., empty CSV)
        }
      } catch (e) {
        console.error(`  Error processing "${config.name}" CSV (${file.getName()}) for BigQuery: ${e.message}`);
        return false; // Processing failed
      }
    }
  }
  return null; // CSV not recognized by any configuration
}


/**
 * Converts a CSV file from Drive to newline-delimited JSON using a specific configuration.
 * Adapted from processAttachmentToJsonGeneric.
 * @param {DriveApp.File} file The Google Drive file to process.
 * @param {object} config The configuration object for the current CSV type.
 * @returns {string|null} The Google Drive File ID of the created JSON file, or null if an error occurred or CSV was empty.
*/
function processFileToJsonGeneric(file, config) {
  try {
    const csvData = Utilities.parseCsv(file.getBlob().getDataAsString());
    if (csvData.length <= 1) {
      console.warn(`  CSV data empty or only headers for file: "${file.getName()}". Skipping conversion.`);
      return null;
    }

    // Use specific fieldMap from config
    const headers = csvData.shift().map(header => standardizeFieldName(header, config.fieldMap));
    const jsonData = csvData.map((row) => {
      const jsonObj = {};
      headers.forEach((header, colIndex) => {
        // Use specific timestampFields and integerFields from config
        jsonObj[header] = handleEmptyValues(row[colIndex], config.timestampFields.includes(header), config.integerFields.includes(header));
      });
      return JSON.stringify(jsonObj);
    });

    const jsonString = jsonData.join("\n");
    const fileName = file.getName().replace(/\.[^/.]+$/, "") + "_converted.json";
    const tempFile = DriveApp.getFolderById(folderId).createFile(fileName, jsonString);

    return tempFile.getId();
  } catch (error) {
    console.error(`  Error converting file "${file ? file.getName() : 'unknown'}" to JSON:`, error.message);
    throw error; // Re-throw to be caught by calling function for file-level error handling
  }
}

/**
 * Processes a single value from the CSV based on its expected type.
 * Handles empty strings, attempts timestamp parsing (UTC), and integer parsing.
 * @param {string} value The string value from the CSV cell.
 * @param {boolean} isTimestamp Whether the column is expected to be a TIMESTAMP.
 * @param {boolean} isInteger Whether the column is expected to be an INTEGER.
 * @return {any} The processed value (string, number, or null).
 */
function handleEmptyValues(value, isTimestamp, isInteger) {
  if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
    return null;
  }

  const trimmedValue = value.trim();

  if (isTimestamp) {
    let year, month, day, hour, minute, second = '00';
    let match = trimmedValue.match(/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})$/); // DD/MM/YYYY HH:MM
    if (match) {
      day = match[1]; month = match[2]; year = match[3]; hour = match[4]; minute = match[5];
    } else {
      match = trimmedValue.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/); // YYYY-MM-DD HH:MM:SS
      if (match) {
        year = match[1]; month = match[2]; day = match[3]; hour = match[4]; minute = match[5]; second = match[6];
      } else {
        match = trimmedValue.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/); // YYYY-MM-DD HH:MM
        if (match) {
          year = match[1]; month = match[2]; day = match[3]; hour = match[4]; minute = match[5]; second = '00';
        } else {
          return null;
        }
      }
    }
    // Construct a reliable date string for Date object, ensuring month is 0-indexed for JS Date constructor if building manually
    // For 'YYYY-MM-DDTHH:mm:ssZ' format, directly adding 'Z' makes it unambiguous UTC
    const reliableDateString = `${year}-${month}-${day}T${hour}:${minute}:${second}.000Z`; // Adding .000Z for milliseconds and explicit UTC
    const date = new Date(reliableDateString);
    if (!isNaN(date.getTime())) {
      // Return in BigQuery's preferred TIMESTAMP string format (ISO 8601 extended with 'Z' for UTC if needed)
      return Utilities.formatDate(date, "UTC", "yyyy-MM-dd'T'HH:mm:ss'Z'");
    }
    return null;
  }

  if (isInteger) {
    const parsedInt = parseInt(trimmedValue, 10);
    if (!isNaN(parsedInt)) {
      return parsedInt;
    }
    return null;
  }
  return trimmedValue;
}

/**
 * Loads a newline-delimited JSON file into a BigQuery staging table based on configuration.
 * @param {string} jsonFileId The Google Drive File ID of the JSON file.
 * @param {object} config The configuration object for the current CSV type.
 */
function loadJsonToBigQueryGeneric(jsonFileId, config) {
  try {
    const file = DriveApp.getFileById(jsonFileId);
    const jsonDataBlob = file.getBlob();

    const loadJob = {
      configuration: {
        load: {
          destinationTable: { projectId, datasetId: config.stagingDatasetId, tableId: config.stagingTableId },
          sourceFormat: "NEWLINE_DELIMITED_JSON",
          // WRITE_TRUNCATE is correct for staging tables, as each new load replaces the previous one.
          writeDisposition: "WRITE_TRUNCATE", // Each type has its own staging table
          autodetect: true
        }
      }
    };

    console.log(`    Initiating BigQuery load to ${config.stagingDatasetId}.${config.stagingTableId}...`);
    const job = BigQuery.Jobs.insert(loadJob, projectId, jsonDataBlob);
    waitForJobCompletion(job);
    console.log("    JSON data successfully loaded to staging.");
    
    // Get actual columns from staging table after load
    const stagingColumns = getTableColumns(config.stagingDatasetId, config.stagingTableId);
    console.log(`    Detected ${stagingColumns.length} columns in staging table.`);
    
    // Ensure target table has all columns from staging
    ensureTargetTableColumns(config, stagingColumns);

  } catch (error) {
    console.error(`    Error loading JSON to BigQuery staging for ${config.name}: ${error.message}`);
    MailApp.sendEmail({ // Send detailed email for BigQuery failures immediately
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Staging Load Failed for ${config.name}`,
      body: `An error occurred while loading JSON into BigQuery staging table ${config.stagingDatasetId}.${config.stagingTableId}: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    // Log error to PipelineRuns (best effort)
    if (currentRunId) {
      logPipelineRun(scriptName, currentRunId, 'ERROR', 'ERROR', 'Error loading data: ' + error.message, null, null, null, null, null);
    }
    throw error; // Re-throw to propagate error to message-level handler
  } finally {
    try { if (jsonFileId) DriveApp.getFileById(jsonFileId).setTrashed(true); }
    catch (cleanUpError) { console.warn(`    Error deleting temporary JSON file ${jsonFileId}:`, cleanUpError.message); }
  }
}

/**
 * Standardizes CSV header names to match BigQuery schema field names using a specific field map.
 * @param {string} header The raw header string from the CSV.
 * @param {object} fieldMap The field map specific to the CSV type.
 * @returns {string} The standardized BigQuery-ready field name.
 */
function standardizeFieldName(header, fieldMap) {
  return fieldMap[header.trim()] || header.trim().replace(/\s+/g, "_");
}

/**
 * Get all column names from a BigQuery table
 */
function getTableColumns(datasetId, tableId) {
  try {
    const table = BigQuery.Tables.get(projectId, datasetId, tableId);
    const columns = table.schema.fields.map(field => field.name);
    return columns;
  } catch (error) {
    console.error(`Error getting columns from ${datasetId}.${tableId}: ${error.message}`);
    throw error;
  }
}

/**
 * Ensure target table has all columns that exist in staging table
 * Adds missing columns with appropriate types, one at a time to ensure partial success
 */
function ensureTargetTableColumns(config, stagingColumns) {
  try {
    // Get FRESH copy of target table right before update (in case it was modified)
    let targetTable = BigQuery.Tables.get(projectId, config.targetDatasetId, config.targetTableId);
    let existingColumns = targetTable.schema.fields.map(f => f.name);
    
    // Case-insensitive column comparison
    const existingColumnsLower = new Set(existingColumns.map(c => c.toLowerCase()));
    const missingColumns = stagingColumns.filter(col => !existingColumnsLower.has(col.toLowerCase()));
    
    if (missingColumns.length === 0) {
      console.log(`    Target table already has all columns.`);
      return;
    }
    
    console.log(`    Found ${missingColumns.length} new columns to add: ${missingColumns.join(', ')}`);
    
    // Get staging table schema to copy field types
    const stagingTable = BigQuery.Tables.get(projectId, config.stagingDatasetId, config.stagingTableId);
    const stagingFields = stagingTable.schema.fields;
    
    let fieldsAddedCount = 0;
    let fieldsFailed = [];
    
    // Add columns ONE AT A TIME to ensure partial success even if some already exist
    for (const colName of missingColumns) {
      try {
        // Get fresh target table for each column addition
        targetTable = BigQuery.Tables.get(projectId, config.targetDatasetId, config.targetTableId);
        existingColumns = targetTable.schema.fields.map(f => f.name);
        
        // Case-insensitive check: does this column now exist?
        const existingLower = new Set(existingColumns.map(c => c.toLowerCase()));
        if (existingLower.has(colName.toLowerCase())) {
          console.log(`    Field ${colName} already exists in target (case-insensitive match), skipping.`);
          continue;
        }
        
        const stagingField = stagingFields.find(f => f.name === colName);
        const newField = {
          name: colName,
          type: stagingField ? stagingField.type : 'STRING',
          mode: 'NULLABLE'
        };
        
        // Create new schema with just this one field added
        const updatedSchema = targetTable.schema.fields.slice();
        updatedSchema.push(newField);
        
        targetTable.schema.fields = updatedSchema;
        BigQuery.Tables.update(targetTable, projectId, config.targetDatasetId, config.targetTableId);
        console.log(`    Successfully added field ${colName} to target table.`);
        fieldsAddedCount++;
        
      } catch (fieldError) {
        // If the error is about a field already existing, continue (it was added by another process)
        if (fieldError.message && fieldError.message.includes('already exists')) {
          console.log(`    Field ${colName} already exists (concurrent update): ${fieldError.message}. Continuing.`);
          fieldsAddedCount++; // Count as successful since field exists
        } else {
          console.error(`    Failed to add field ${colName}: ${fieldError.message}`);
          fieldsFailed.push(colName);
          // Continue to attempt adding remaining fields
        }
      }
    }
    
    console.log(`    Field addition complete: ${fieldsAddedCount} fields successfully added or confirmed, ${fieldsFailed.length} failures.`);
    if (fieldsFailed.length > 0) {
      console.warn(`    Fields that failed: ${fieldsFailed.join(', ')}`);
    }
    
  } catch (error) {
    console.error(`Error ensuring target table columns: ${error.message}`);
    throw error;
  }
}

/**
 * Merges data from the staging table into the target table in BigQuery based on configuration.
 * @param {object} config The configuration object for the current CSV type.
 */
function mergeTablesInBigQueryGeneric(config) {
  try {
    // Get actual columns from both tables for case-insensitive matching
    const stagingColumns = getTableColumns(config.stagingDatasetId, config.stagingTableId);
    const targetColumns = getTableColumns(config.targetDatasetId, config.targetTableId);
    
    console.log(`    Staging table has ${stagingColumns.length} columns, target table has ${targetColumns.length} columns.`);
    
    // Build a case-insensitive map of target columns for matching
    const targetColumnsLower = new Map(targetColumns.map(c => [c.toLowerCase(), c]));
    
    // Get all staging columns, using the actual target column name if it exists (case-insensitive)
    const mergeColumns = stagingColumns.map(col => {
      const lowerCol = col.toLowerCase();
      if (targetColumnsLower.has(lowerCol)) {
        return targetColumnsLower.get(lowerCol); // Use the actual target column name
      }
      return null; // Column doesn't exist in target
    }).filter(col => col !== null); // Remove nulls
    
    if (mergeColumns.length < stagingColumns.length) {
      const missing = stagingColumns.filter(col => {
        const targetLower = new Set(targetColumns.map(c => c.toLowerCase()));
        return !targetLower.has(col.toLowerCase());
      });
      console.warn(`    Warning: ${missing.length} staging columns not in target: ${missing.join(', ')}`);
      console.log(`    Will merge ${mergeColumns.length} columns that exist in both tables.`);
    }
    
    const primaryKeys = Array.isArray(config.primaryKeyForMerge) ? config.primaryKeyForMerge : [config.primaryKeyForMerge];
    const onClause = primaryKeys.map(pk => `T.${pk} = H.${pk}`).join(" AND ");

    const updateSetClause = mergeColumns
      .filter(col => !primaryKeys.includes(col)) // Don't update primary keys
      .map(col => {
        if (config.timestampFields.includes(col)) {
          return `T.${col} = SAFE_CAST(H.${col} AS TIMESTAMP)`;
        } else {
          return `T.${col} = H.${col}`;
        }
      })
      .join(",\n        ");

    const insertColumns = mergeColumns.join(", ");
    const insertValues = mergeColumns.map(col => {
      if (config.timestampFields.includes(col)) {
        return `SAFE_CAST(H.${col} AS TIMESTAMP)`;
      } else {
        return `H.${col}`;
      }
    }).join(", ");

    const query = `
      MERGE \`${projectId}.${config.targetDatasetId}.${config.targetTableId}\` T
      USING \`${projectId}.${config.stagingDatasetId}.${config.stagingTableId}\` H
      ON ${onClause}
      WHEN MATCHED THEN
        UPDATE SET
        ${updateSetClause}
      WHEN NOT MATCHED THEN
        INSERT (${insertColumns}) VALUES (${insertValues});
    `;

    console.log(`    Initiating BigQuery MERGE for ${config.name} into ${config.targetDatasetId}.${config.targetTableId} (${mergeColumns.length} columns).`);
    const job = BigQuery.Jobs.insert({ configuration: { query: { query, useLegacySql: false } } }, projectId);
    const completedJob = waitForJobCompletion(job);
    
    // Extract row counts from job statistics
    const numDmlAffectedRows = completedJob.statistics && completedJob.statistics.query && completedJob.statistics.query.numDmlAffectedRows 
      ? parseInt(completedJob.statistics.query.numDmlAffectedRows) : 0;
    
    console.log(`    BigQuery MERGE for ${config.name} completed successfully! Rows affected: ${numDmlAffectedRows}`);
    return numDmlAffectedRows;

  } catch (error) {
    console.error(`    Error merging tables in BigQuery for ${config.name}: ${error.message}`);
    MailApp.sendEmail({ // Send detailed email for BigQuery failures immediately
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Merge Operation Failed for ${config.name}`,
      body: `An error occurred while merging tables in BigQuery for ${config.targetDatasetId}.${config.targetTableId}: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    throw error; // Re-throw to propagate error to file-level error handling
  }
}

/**
 * Waits for a BigQuery job (load or query) to complete, and checks for errors.
 * @param {object} job The BigQuery job object returned by BigQuery.Jobs.insert.
 * @throws {Error} If the BigQuery job fails or times out.
 */
function waitForJobCompletion(job) {
  const jobId = job.jobReference.jobId;
  const maxAttempts = 60; // Max 60 * 5 seconds = 5 minutes wait
  let attempts = 0;

  while (job.status && job.status.state !== "DONE" && attempts < maxAttempts) {
    Utilities.sleep(5000);
    job = BigQuery.Jobs.get(projectId, jobId);
    attempts++;
  }
  if (job.status.state !== "DONE") {
    throw new Error(`BigQuery job ${jobId} timed out after ${attempts * 5} seconds.`);
  }
  if (job.status.errorResult) {
    const errorDetails = JSON.stringify(job.status.errors, null, 2);
    throw new Error(`BigQuery job ${jobId} failed: ${job.status.errorResult.message}. Details: \n${errorDetails}`);
  }
  return job;
}



// Centralized PipelineRuns logger using MERGE to align with Python scripts
function logPipelineRun(pipelineName, runId, status, logLevel, message, windowStartIso, windowEndIso, rowsMerged, errorCode, contextObj) {
  try {
    let durationSeconds = null;
    if ((status === 'SUCCESS' || status === 'ERROR') && scriptStartTime) {
      durationSeconds = (new Date().getTime() - scriptStartTime.getTime()) / 1000.0;
    }

    const query = `
      MERGE \`${projectId}.${pipelineRunsDatasetId}.${pipelineRunsTableId}\` T
      USING (
        SELECT
          @pipeline AS PipelineName,
          @ws AS WindowStart,
          @we AS WindowEnd,
          @rows AS RowsMerged,
          @level AS LogLevel,
          @msg AS Message,
          @runid AS RunID,
          @status AS Status,
          @err AS ErrorCode,
          @duration AS DurationSeconds,
          CAST(NULL AS JSON) AS Context
      ) S
      ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID
      WHEN MATCHED THEN UPDATE SET
          T.WindowStart = COALESCE(S.WindowStart, T.WindowStart),
          T.WindowEnd   = COALESCE(S.WindowEnd,   T.WindowEnd),
          T.RowsMerged  = COALESCE(S.RowsMerged,  T.RowsMerged),
          T.LogLevel    = COALESCE(S.LogLevel,    T.LogLevel),
          T.Message     = COALESCE(S.Message,     T.Message),
          T.Status      = COALESCE(S.Status,      T.Status),
          T.ErrorCode   = COALESCE(S.ErrorCode,   T.ErrorCode),
          T.DurationSeconds = COALESCE(S.DurationSeconds, T.DurationSeconds),
          T.Context     = COALESCE(S.Context,     T.Context)
      WHEN NOT MATCHED THEN
        INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, DurationSeconds, Context)
        VALUES (CURRENT_TIMESTAMP(), S.PipelineName, S.WindowStart, S.WindowEnd, S.RowsMerged, S.LogLevel, S.Message, S.RunID, S.Status, S.ErrorCode, S.DurationSeconds, S.Context)
    `;

    const queryRequest = {
      query: query,
      useLegacySql: false,
      parameterMode: 'NAMED',
      queryParameters: [
        { name: 'pipeline', parameterType: { type: 'STRING' }, parameterValue: { value: pipelineName } },
        { name: 'ws', parameterType: { type: 'TIMESTAMP' }, parameterValue: { value: windowStartIso } },
        { name: 'we', parameterType: { type: 'TIMESTAMP' }, parameterValue: { value: windowEndIso } },
        { name: 'rows', parameterType: { type: 'INT64' }, parameterValue: { value: (rowsMerged !== null && rowsMerged !== undefined) ? rowsMerged.toString() : null } },
        { name: 'level', parameterType: { type: 'STRING' }, parameterValue: { value: logLevel } },
        { name: 'msg', parameterType: { type: 'STRING' }, parameterValue: { value: message } },
        { name: 'runid', parameterType: { type: 'STRING' }, parameterValue: { value: runId } },
        { name: 'status', parameterType: { type: 'STRING' }, parameterValue: { value: status } },
        { name: 'err', parameterType: { type: 'STRING' }, parameterValue: { value: errorCode } },
        { name: 'duration', parameterType: { type: 'FLOAT64' }, parameterValue: { value: durationSeconds } }
      ]
    };

    console.log(`Logging pipeline run: ${status} - ${message} (RunID: ${runId})`);
    const job = BigQuery.Jobs.query(queryRequest, projectId);
    
    if (job.jobComplete) {
      console.log(`Pipeline run logged successfully. Job ID: ${job.jobReference.jobId}`);
    } else {
      console.warn(`Pipeline run log job timed out (not complete). Job ID: ${job.jobReference.jobId}`);
    }

  } catch (e) {
    console.warn('logPipelineRun failed: ' + e.message);
    console.warn('Stack trace: ' + e.stack);
  }
}

function escapeSqlLiteral(s) {
  return s.replace(/'/g, "''");
}

/**
 * The entry point for the Google Apps Script execution.
 */
function main() {
  currentRunId = Utilities.getUuid();
  scriptStartTime = new Date();
  logPipelineRun(scriptName, currentRunId, 'RUNNING', 'INFO', 'Pipeline run started', null, null, null, null, null);
  processDriveFiles();
}
