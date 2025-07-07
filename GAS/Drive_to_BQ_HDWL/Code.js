// --- GLOBAL VARIABLES ---
var scriptName = "Automated Datapipe - HelpDeskAllNOC_and_Worklog_DriveSource";
var projectId = "pccw-internal-virt-agent-uat";
var folderId = "1-CN9TVdXLQlG033djKVG5slzbhADbpdA"; // Assuming this is for temporary JSON files on Drive
var errorNotificationEmails = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com";

// --- NEW DRIVE FOLDER IDs ---
var sourceDriveFolderId = "15aWB6BmkjbySqHb5NWkaOn6fMQIZ5an0";
var archiveDriveFolderId = "16RazUSdV7klL8ZAqNqVNUx7mWtpKkZi-";


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
      "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy"
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
      "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRno": "SRno", "ReportedBy": "ReportedBy"
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
      "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By"
    ],
    primaryKeyForMerge: "WorkLog_ID", // WorkLog_ID is the primary key for WL
    fieldMap: { // Header mapping for Worklog CSV
      "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
      "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
      "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
      "LastModifiedBy": "Last_Modified_By"
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

    if (processStatus === true) {
      totalFilesProcessedSuccessfully++;
      totalCSVsLoadedToBigQuery++; // Increment if BigQuery load/merge was successful for this CSV

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
  console.log("Data pipeline run complete.");
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
          mergeTablesInBigQueryGeneric(config);
          console.log(`  Successfully processed and loaded "${config.name}" data.`);
          return true; // Successfully handled this attachment
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

  } catch (error) {
    console.error(`    Error loading JSON to BigQuery staging for ${config.name}: ${error.message}`);
    MailApp.sendEmail({ // Send detailed email for BigQuery failures immediately
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Staging Load Failed for ${config.name}`,
      body: `An error occurred while loading JSON into BigQuery staging table ${config.stagingDatasetId}.${config.stagingTableId}: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
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
 * Merges data from the staging table into the target table in BigQuery based on configuration.
 * @param {object} config The configuration object for the current CSV type.
 */
function mergeTablesInBigQueryGeneric(config) {
  try {
    const primaryKeys = Array.isArray(config.primaryKeyForMerge) ? config.primaryKeyForMerge : [config.primaryKeyForMerge];
    const onClause = primaryKeys.map(pk => `T.${pk} = H.${pk}`).join(" AND ");

    const updateSetClause = config.allColumns
      .filter(col => !primaryKeys.includes(col)) // Don't update primary keys
      .map(col => `T.${col} = H.${col}`)
      .join(",\n        ");

    const insertColumns = config.allColumns.join(", ");
    const insertValues = config.allColumns.map(col => `H.${col}`).join(", ");

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

    console.log(`    Initiating BigQuery MERGE for ${config.name} into ${config.targetDatasetId}.${config.targetTableId}.`);
    const job = BigQuery.Jobs.insert({ configuration: { query: { query, useLegacySql: false } } }, projectId);
    waitForJobCompletion(job);
    console.log(`    BigQuery MERGE for ${config.name} completed successfully!`);

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
}

/**
 * The entry point for the Google Apps Script execution.
 */
function main() {
  processDriveFiles();
}
