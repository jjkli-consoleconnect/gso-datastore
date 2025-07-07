// --- GLOBAL VARIABLES ---
var scriptName = "Automated Datapipe - HelpDeskAllNOC";
var subject = "BigQuery - HelpDesk ALL NOC"; 
var sender = "noreply-bmchelix@onbmc.com";
var label = "CloudWatch"; 
var projectId = "pccw-internal-virt-agent-uat";
var datasetId = "Staging"; //staging
var tableId = "HelpDeskAllNOC"; // BigQuery Staging table (will be truncated and loaded)
var targetDatasetId = "GSO"; // BigQuery Target dataset
var targetTableId = "HelpDeskAllNOC"; // BigQuery Target table (will be merged into)
var folderId = "1-CN9TVdXLQlG033djKVG5slzbhADbpdA"; 
var errorNotificationEmails = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com";
var archivedLabel = "ArchivedReports"; 

// --- FUNCTIONS ---

/**
 * Main function to search for emails, process attachments, and trigger BigQuery loads.
 */
function searchForEmailAndAttachments() {
  const cleanSubject = subject.trim();
  const cleanLabel = label.trim();
  const cleanSender = sender.trim();
  const searchQuery = `subject:"${cleanSubject}" from:${cleanSender} label:"${cleanLabel}" is:unread`;
  console.log(`Starting data pipeline run. Searching for emails with query: "${searchQuery}"`);

  const threads = GmailApp.search(searchQuery);
  console.log("Found " + threads.length + " unread email threads matching criteria.");

  if (threads.length === 0) {
    console.log("No new emails found conforming to search criteria. Exiting.");
    return; 
  }

  threads.sort((a, b) => a.getLastMessageDate().getTime() - b.getLastMessageDate().getTime());

  let totalThreadsArchivedSuccessfully = 0;
  let totalMessagesWithProcessedCSVs = 0; // Number of messages where CSV data was successfully ingested
  let totalAttachmentsLoadedToBigQuery = 0; // Total successful BigQuery loads
  let anyProcessingIssueEncountered = false; // Flag for any non-critical failure that warrants a warning email

  // Loop through each email thread found
  for (const thread of threads) {
    const threadSubject = thread.getFirstMessageSubject().trim();
    console.log(`\n--- Processing Thread ID: ${thread.getId()} (Subject: "${threadSubject}") ---`);

    // Basic subject validation in case search returns unexpected items
    if (threadSubject !== cleanSubject) {
        console.warn(`Skipping thread ${thread.getId()} due to subject mismatch. Expected: "${cleanSubject}" Got: "${threadSubject}".`);
        anyProcessingIssueEncountered = true;
        continue; // Move to the next thread
    }

    const messages = thread.getMessages();
    // Sort messages within this thread from OLDEST to NEWEST.
    messages.sort((a, b) => a.getDate().getTime() - b.getDate().getTime());

    let currentThreadFullyProcessed = true; // Assume this thread will succeed, unless a specific Message fails

    let skippedReadMessagesInThread = 0;
    let skippedNoDataMessagesInThread = 0; // Messages that are unread but have no CSV data/attachments
    let failedProcessingMessagesInThread = 0; // Unread messages that attempted processing but failed

    // Loop through each individual message within the thread
    for (const message of messages) {
      if (!message.isUnread()) {
        skippedReadMessagesInThread++;
        continue; // Skip messages that are already read/processed
      }

      let messageProcessedSuccessfully = false; // Flag for current message's processing success

      const attachments = message.getAttachments();
      let hasRelevantAttachment = false;

      if (attachments.length > 0) {
        for (const attachment of attachments) {
          if (attachment.getName().toLowerCase().endsWith(".csv")) {
            hasRelevantAttachment = true;
            console.log(`  Processing CSV attachment "${attachment.getName()}" from Message ID: ${message.getId()}`);
            try {
              const jsonFileId = processAttachmentToJson(attachment);
              if (jsonFileId) {
                try {
                    loadJsonToBigQuery(jsonFileId);
                    messageProcessedSuccessfully = true;
                    totalAttachmentsLoadedToBigQuery++;
                    totalMessagesWithProcessedCSVs++; // Only count actual CSV data ingestion
                    message.markRead(); // Mark this message as READ upon SUCCESSFUL processing
                    break; // Process only the first CSV per message
                } catch (bqError) {
                    console.error(`  BigQuery processing failed for attachment "${attachment.getName()}" Message ID: ${message.getId()}: ${bqError.message}. This message remains unread.`);
                    failedProcessingMessagesInThread++;
                    currentThreadFullyProcessed = false;
                    anyProcessingIssueEncountered = true;
                }
              } else {
                console.error(`  CSV to JSON conversion failed for attachment "${attachment.getName()}" Message ID: ${message.getId()}. This message remains unread.`);
                failedProcessingMessagesInThread++;
                currentThreadFullyProcessed = false;
                anyProcessingIssueEncountered = true;
              }
            } catch (jsonConvertError) {
              console.error(`  Critical error during JSON conversion for attachment "${attachment.getName()}" Message ID: ${message.getId()}: ${jsonConvertError.message}. This message remains unread.`);
              failedProcessingMessagesInThread++;
              currentThreadFullyProcessed = false;
              anyProcessingIssueEncountered = true;
            }
          }
        } // End of attachments loop
      }

      if (!hasRelevantAttachment) { // Unread message has no CSV attachments or no attachments at all
        skippedNoDataMessagesInThread++;
        message.markRead(); // Mark message as read, assuming it doesn't need data processing
      } else if (!messageProcessedSuccessfully) { // Had CSV, but processing failed
        failedProcessingMessagesInThread++; // Count again for general failure
      }
    } // End of message loop

    // Post-thread processing summary and archiving decision
    if (skippedReadMessagesInThread > 0) {
        console.log(`  Skipped ${skippedReadMessagesInThread} messages as they were already read prior to this run.`);
    }
    if (skippedNoDataMessagesInThread > 0) {
        console.log(`  Skipped ${skippedNoDataMessagesInThread} unread messages as they contained no relevant CSV data (marked as read).`);
    }
    if (failedProcessingMessagesInThread > 0) {
        console.warn(`  ${failedProcessingMessagesInThread} unread messages in this thread failed processing and remain unread for retry.`);
        currentThreadFullyProcessed = false; // Ensure this is explicitly set if there were failed messages
    }

    if (currentThreadFullyProcessed) {
        // CRITICAL FIX: Add a short delay and re-fetch the thread to allow Gmail to update its status
        console.log(`  All relevant messages in Thread ID: ${thread.getId()} processed. Waiting 5 seconds for Gmail state update...`);
        Utilities.sleep(5000); // Wait for 5 seconds

        // Re-fetch the thread object to get its latest state from the server
        const refreshedThread = GmailApp.getThreadById(thread.getId());

        if (!refreshedThread.isUnread()) { // Final check after delay and refresh
            const archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);
            const currentLabelObj = GmailApp.getUserLabelByName(label);

            if (!archivedLabelObj) {
                console.error(`Archiving failed: Label "${archivedLabel}" not found for Thread ID: ${thread.getId()}.`);
                anyProcessingIssueEncountered = true;
            } else {
                if (currentLabelObj) refreshedThread.removeLabel(currentLabelObj);
                refreshedThread.addLabel(archivedLabelObj);
                console.log(`---> Thread ID: ${refreshedThread.getId()} fully processed and moved to "${archivedLabel}".`);
                totalThreadsArchivedSuccessfully++;
            }
        } else {
            console.warn(`---> Thread ID: ${thread.getId()} *still* shows unread messages after processing and delay. NOT archiving. It will retry in next run.`);
            anyProcessingIssueEncountered = true; // Still an issue, will trigger warning email
        }
    } else {
        console.warn(`---> Thread ID: ${thread.getId()} NOT fully processed due to errors/unprocessed messages. Keeping "${label}" label for retry.`);
    }
  } // End of thread loop

  console.log("\n--- Overall Processing Summary ---");
  console.log(`Total threads initially found (unread): ${threads.length}`);
  console.log(`Total threads fully processed and archived: ${totalThreadsArchivedSuccessfully}`);
  console.log(`Total unique messages with processed CSVs: ${totalMessagesWithProcessedCSVs}`);
  console.log(`Total CSV attachments loaded to BigQuery: ${totalAttachmentsLoadedToBigQuery}`);

  if (anyProcessingIssueEncountered || totalThreadsArchivedSuccessfully < threads.length) {
    const warningBody = `Some emails/threads were not fully processed or had errors during processing.
      \nPlease check Google Apps Script logs for "${scriptName}" for details.`;
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: `WARNING in ${scriptName}: Processing Issues Detected`,
      body: warningBody
    });
    console.warn("A warning email has been sent due to partial or failed processing.");
  } else {
    console.log("All matching pending emails processed successfully. No warning email sent.");
  }
  console.log("Data pipeline run complete.");
}

/**
 * Converts a CSV attachment to newline-delimited JSON and stores it in Google Drive.
 * @param {GmailApp.GmailAttachment} attachment The email attachment to process.
 * @returns {string|null} The Google Drive File ID of the created JSON file, or null if an error occurred.
*/
function processAttachmentToJson(attachment) {
  try {
    const csvData = Utilities.parseCsv(attachment.getDataAsString());
    if (csvData.length <= 1) {
      console.warn(`  CSV data empty or only headers for attachment: "${attachment.getName()}". Skipping conversion.`);
      return null;
    }

    const headers = csvData.shift().map(header => standardizeFieldName(header));
    const jsonData = csvData.map((row) => {
      const jsonObj = {};
      headers.forEach((header, colIndex) => {
        jsonObj[header] = handleEmptyValues(row[colIndex], isTimestampField(header), isIntegerField(header));
      });
      return JSON.stringify(jsonObj);
    });

    const jsonString = jsonData.join("\n");
    const fileName = attachment.getName().replace(/\.[^/.]+$/, "") + "_converted.json";
    const file = DriveApp.getFolderById(folderId).createFile(fileName, jsonString);

    return file.getId();
  } catch (error) {
    console.error(`  Error converting attachment "${attachment ? attachment.getName() : 'unknown'}" to JSON:`, error.message);
    throw error; // Re-throw to be caught by calling function for message-level error handling
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
    const reliableDateString = `${year}-${month}-${day}T${hour}:${minute}:${second}Z`;
    const date = new Date(reliableDateString);
    if (!isNaN(date.getTime())) {
      return Utilities.formatDate(date, "UTC", "yyyy-MM-dd'T'HH:mm:ss");
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
 * Loads a newline-delimited JSON file into a BigQuery staging table.
 * @param {string} jsonFileId The Google Drive File ID of the JSON file.
 */
function loadJsonToBigQuery(jsonFileId) {
  try {
    const file = DriveApp.getFileById(jsonFileId);
    const jsonDataBlob = file.getBlob();

    const loadJob = {
      configuration: {
        load: {
          destinationTable: { projectId, datasetId, tableId },
          sourceFormat: "NEWLINE_DELIMITED_JSON",
          writeDisposition: "WRITE_TRUNCATE",
          autodetect: true
        }
      }
    };

    console.log(`    Initiating BigQuery load to ${datasetId}.${tableId}...`);
    const job = BigQuery.Jobs.insert(loadJob, projectId, jsonDataBlob);
    waitForJobCompletion(job);
    console.log("    JSON data successfully loaded to staging.");

    mergeTablesInBigQuery();
  } catch (error) {
    console.error(`    Error loading JSON to BigQuery staging: ${error.message}`);
    MailApp.sendEmail({ // Send detailed email for BigQuery failures immediately
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Staging Load Failed`,
      body: `An error occurred while loading JSON into BigQuery staging table: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    throw error; // Re-throw to propagate error to message-level handler
  } finally {
    try { if (jsonFileId) DriveApp.getFileById(jsonFileId).setTrashed(true); }
    catch (cleanUpError) { console.warn(`    Error deleting temporary JSON file ${jsonFileId}:`, cleanUpError.message); }
  }
}

/**
 * Standardizes CSV header names to match BigQuery schema field names.
 * @param {string} header The raw header string from the CSV.
 * @returns {string} The standardized BigQuery-ready field name.
 */
function standardizeFieldName(header) {
  const fieldMap = {
    "IncidentNumber": "Incident_Number", "casetype": "CaseType", "Assigned Group": "Assigned_Group",
    "Categorization Tier 1": "Categorization_Tier_1", "Categorization Tier 2": "Categorization_Tier_2",
    "Categorization Tier 3": "Categorization_Tier_3", "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
    "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update", "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
    "Initial Response Time": "Initial_Response_Time", "Second Response Time": "Second_Response_Time",
    "Third Response Time": "Third_Response_Time", "Prod ID": "Prod_ID", "FaultCause": "Fault_Cause",
    "Closed Date": "Closed_Date", "Submit Date": "Submit_Date", "ClosedBy": "Closed_By",
    "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRNo": "SRno"
    // 'LastModifiedDate' will be handled by the default conversion (removes leading/trailing spaces)
  };
  return fieldMap[header.trim()] || header.trim().replace(/\s+/g, "_");
}

/**
 * Merges data from the staging table into the target table in BigQuery.
 */
function mergeTablesInBigQuery() {
  try {
    const allColumns = [
      "Incident_Number", "Status", "CaseType", "Assigned_Group", "Categorization_Tier_1",
      "Categorization_Tier_2", "Categorization_Tier_3", "GCSC_1st_Customer_Update",
      "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update", "Initial_Response_Time",
      "Second_Response_Time", "Third_Response_Time", "Prod_ID", "Fault_Cause",
      "Closed_Date", "Submit_Date", "Assignee", "Closed_By", "Submitter", "TrueMTTR_mins",
      "Cust_ID", "Carrier", "Customer_Name", "SRno", "LastResolvedDate", "ReportedDate",
      "RespondedDate", "FaultCauseDetail",
      "LastModifiedDate" // Field added as per request
    ];
    const updateSetClause = allColumns.filter(col => col !== "Incident_Number").map(col => `T.${col} = H.${col}`).join(",\n        ");
    const insertColumns = allColumns.join(", ");
    const insertValues = allColumns.map(col => `H.${col}`).join(", ");

    const query = `
      MERGE \`${projectId}.${targetDatasetId}.${targetTableId}\` T
      USING \`${projectId}.${datasetId}.${tableId}\` H
      ON T.Incident_Number = H.Incident_Number
      WHEN MATCHED THEN
        UPDATE SET
        ${updateSetClause}
      WHEN NOT MATCHED THEN
        INSERT (${insertColumns}) VALUES (${insertValues});
    `;

    console.log(`    Initiating BigQuery MERGE into ${targetDatasetId}.${targetTableId}.`);
    const job = BigQuery.Jobs.insert({ configuration: { query: { query, useLegacySql: false } } }, projectId);
    waitForJobCompletion(job);
    console.log("    BigQuery MERGE completed successfully!");

  } catch (error) {
    console.error(`    Error merging tables in BigQuery: ${error.message}`);
    MailApp.sendEmail({ // Send detailed email for BigQuery failures immediately
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Merge Operation Failed`,
      body: `An error occurred while merging tables in BigQuery: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    throw error; // Re-throw to propagate error to message-level handler
  }
}

/**
 * Checks if a standardized header name corresponds to a BigQuery TIMESTAMP field.
 * @param {string} header The standardized header name.
 * @returns {boolean} True if it's a timestamp field, false otherwise.
 */
function isTimestampField(header) {
  const timestampFields = ["GCSC_1st_Customer_Update", "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update",
                           "Closed_Date", "Submit_Date", "LastResolvedDate", "ReportedDate", "RespondedDate",
                           "LastModifiedDate" // Field added as per request
                          ];
  return timestampFields.includes(header);
}

/**
 * Checks if a standardized header name corresponds to a BigQuery INTEGER field.
 * @param {string} header The standardized header name.
 * @returns {boolean} True if it's an integer field, false otherwise.
 */
function isIntegerField(header) {
  const integerFields = ["Initial_Response_Time", "Second_Response_Time", "Third_Response_Time", "TrueMTTR_mins"];
  return integerFields.includes(header);
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
  searchForEmailAndAttachments();
}