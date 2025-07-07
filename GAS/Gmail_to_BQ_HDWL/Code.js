var scriptName = "Automated Datapipe - HelpDeskAllNOC_and_Worklog";
var subject = "BQ - GSO.HDWL";
var sender = "noreply-bmchelix@onbmc.com";
var label = "CloudWatch";
var projectId = "pccw-internal-virt-agent-uat";
var folderId = "1-CN9TVdXLQlG033djKVG5slzbhADbpdA"; // Make sure this Folder ID is correct and accessible
var errorNotificationEmails = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com";
var archivedLabel = "ArchivedReports"; // Make sure this Gmail Label exists

const csvTypeConfigurations = [
  {
    name: "HelpDeskAllNOC",
    filenamePrefix: "helpdesk",
    stagingDatasetId: "Staging",
    stagingTableId: "HelpDeskAllNOC",
    targetDatasetId: "GSO",
    targetTableId: "HelpDeskAllNOC",
    allColumns: [
      "Incident_Number", "Status", "CaseType", "Assigned_Group", "Categorization_Tier_1",
      "Categorization_Tier_2", "Categorization_Tier_3", "GCSC_1st_Customer_Update",
      "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update", "Initial_Response_Time",
      "Second_Response_Time", "Third_Response_Time", "Prod_ID", "Fault_Cause",
      "Closed_Date", "Submit_Date", "Assignee", "Closed_By", "Submitter", "TrueMTTR_mins",
      "Cust_ID", "Carrier", "Customer_Name", "SRno", "LastResolvedDate", "ReportedDate",
      "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy"
    ],
    primaryKeyForMerge: "Incident_Number",
    fieldMap: {
      "IncidentNumber": "Incident_Number", "casetype": "CaseType", "Assigned Group": "Assigned_Group",
      "Categorization Tier 1": "Categorization_Tier_1", "Categorization Tier 2": "Categorization_Tier_2",
      "Categorization Tier 3": "Categorization_Tier_3", "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
      "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update", "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
      "Initial Response Time": "Initial_Response_Time", "Second Response Time": "Second_Response_Time",
      "Third Response Time": "Third_Response_Time", "Prod ID": "Prod_ID", "FaultCause": "Fault_Cause",
      "Closed Date": "Closed_Date", "Submit Date": "Submit_Date", "ClosedBy": "Closed_By",
      "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRno": "SRno", "ReportedBy": "ReportedBy"
    },
    timestampFields: ["GCSC_1st_Customer_Update", "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update",
                      "Closed_Date", "Submit_Date", "LastResolvedDate", "ReportedDate", "RespondedDate",
                      "LastModifiedDate"],
    integerFields: ["Initial_Response_Time", "Second_Response_Time", "Third_Response_Time", "TrueMTTR_mins"]
  },
  {
    name: "WorkLog",
    filenamePrefix: "worklog",
    stagingDatasetId: "Staging",
    stagingTableId: "WorkLogAllNOC",
    targetDatasetId: "GSO",
    targetTableId: "WorkLogAllNOC",
    allColumns: [
      "Incident_Number", "WorkLog_Type", "WorkLog_ID", "WorkLog_Submit_Date",
      "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By"
    ],
    primaryKeyForMerge: "WorkLog_ID",
    fieldMap: {
      "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
      "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
      "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
      "LastModifiedBy": "Last_Modified_By"
    },
    timestampFields: ["WorkLog_Submit_Date", "Last_Modified_Date"],
    integerFields: []
  }
];

function searchForEmailAndAttachments() {
  const cleanSubject = subject.trim();
  const cleanLabel = label.trim();
  const cleanSender = sender.trim();
  
  const searchQuery = `subject:"${cleanSubject}" from:${cleanSender} label:"${cleanLabel}" is:unread`;
  console.log(`Starting data pipeline run. Exact search query being used: "${searchQuery}"`);

  const threads = GmailApp.search(searchQuery);
  console.log("Found " + threads.length + " unread email threads matching criteria.");

  if (threads.length === 0) {
    console.log("No new emails found conforming to search criteria. Exiting.");
    return;
  }

  threads.sort((a, b) => a.getLastMessageDate().getTime() - b.getLastMessageDate().getTime());

  let totalThreadsArchivedSuccessfully = 0;
  let totalMessagesWithProcessedCSVs = 0;
  let totalAttachmentsLoadedToBigQuery = 0;
  let anyProcessingIssueEncountered = false;

  for (const thread of threads) {
    const threadSubject = thread.getFirstMessageSubject().trim();
    console.log(`\n--- Processing Thread ID: ${thread.getId()} (Subject: "${threadSubject}") ---`);

    if (threadSubject !== cleanSubject) {
        console.warn(`Skipping thread ${thread.getId()} due to subject mismatch. Expected: "${cleanSubject}" Got: "${threadSubject}".`);
        anyProcessingIssueEncountered = true;
        continue;
    }

    const messages = thread.getMessages();
    messages.sort((a, b) => a.getDate().getTime() - b.getDate().getTime());

    let currentThreadFullyProcessed = true;

    let skippedReadMessagesInThread = 0;
    let skippedNoDataMessagesInThread = 0;
    let failedProcessingMessagesInThread = 0;

    for (const message of messages) {
      if (!message.isUnread()) {
        skippedReadMessagesInThread++;
        continue;
      }

      let relevantAttachmentFoundInMessage = false;
      let allRelevantAttachmentsProcessedSuccessfully = true;
      let dataLoadedInThisMessage = false; 

      const attachments = message.getAttachments();

      if (attachments.length > 0) {
        for (const attachment of attachments) {
          if (attachment.getName().toLowerCase().endsWith(".csv")) {
            const processedThisAttachmentResult = processAttachmentByType(attachment, message);

            if (processedThisAttachmentResult === true) { 
              relevantAttachmentFoundInMessage = true;
              dataLoadedInThisMessage = true; 
              totalAttachmentsLoadedToBigQuery++;
            } else if (processedThisAttachmentResult === "SKIPPED_NO_DATA") { 
              relevantAttachmentFoundInMessage = true; 
            } else if (processedThisAttachmentResult === false) { 
              relevantAttachmentFoundInMessage = true;
              allRelevantAttachmentsProcessedSuccessfully = false;
              failedProcessingMessagesInThread++;
              currentThreadFullyProcessed = false;
              anyProcessingIssueEncountered = true;
            } else { 
              console.warn(`    Unrecognized CSV attachment: "${attachment.getName()}" for Message ID: ${message.getId()}`);
            }
          }
        }
      }

      if (relevantAttachmentFoundInMessage && allRelevantAttachmentsProcessedSuccessfully) {
          message.markRead();
          if (dataLoadedInThisMessage) { 
              totalMessagesWithProcessedCSVs++;
          }
      } else if (!relevantAttachmentFoundInMessage) {
          skippedNoDataMessagesInThread++;
          message.markRead();
      } else { 
          // This message had relevant attachments, but some failed to process. Keep it unread for retry.
      }
    } 

    if (skippedReadMessagesInThread > 0) {
        console.log(`    Skipped ${skippedReadMessagesInThread} messages as they were already read prior to this run.`);
    }
    if (skippedNoDataMessagesInThread > 0) {
        console.log(`    Skipped ${skippedNoDataMessagesInThread} unread messages as they contained no relevant CSV data or were unrecognized (marked as read).`);
    }
    if (failedProcessingMessagesInThread > 0) {
        console.warn(`    ${failedProcessingMessagesInThread} unread messages in this thread failed processing and remain unread for retry.`);
        currentThreadFullyProcessed = false;
    }

    if (currentThreadFullyProcessed) {
        console.log(`    All relevant messages in Thread ID: ${thread.getId()} processed. Waiting 5 seconds for Gmail state update...`);
        Utilities.sleep(5000); 

        const refreshedThread = GmailApp.getThreadById(thread.getId());

        if (!refreshedThread.isUnread()) { 
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
            anyProcessingIssueEncountered = true;
        }
    } else {
        console.warn(`---> Thread ID: ${thread.getId()} NOT fully processed due to errors/unprocessed messages. Keeping "${label}" label for retry.`);
    }
  } 

  console.log("\n--- Overall Processing Summary ---");
  console.log(`Total threads initially found (unread): ${threads.length}`);
  console.log(`Total threads fully processed and archived: ${totalThreadsArchivedSuccessfully}`);
  console.log(`Total unique messages with processed CSVs (containing data): ${totalMessagesWithProcessedCSVs}`);
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

function processAttachmentByType(attachment, message) {
  const attachmentNameLower = attachment.getName().toLowerCase();

  for (const config of csvTypeConfigurations) {
    if (attachmentNameLower.startsWith(config.filenamePrefix) && attachmentNameLower.endsWith(".csv")) {
      console.log(`    Identified "${config.name}" CSV: "${attachment.getName()}"`);
      try {
        const jsonFileId = processAttachmentToJsonGeneric(attachment, config);
        if (jsonFileId) { 
          loadJsonToBigQueryGeneric(jsonFileId, config);
          mergeTablesInBigQueryGeneric(config);
          console.log(`    Successfully processed and loaded "${config.name}" data.`);
          return true; 
        } else { 
          console.log(`    Successfully skipped empty/headers-only CSV: ${attachment.getName()}. No data to load.`);
          return "SKIPPED_NO_DATA"; 
        }
      } catch (e) {
        console.error(`    Error processing "${config.name}" CSV (${attachment.getName()}): ${e.message}`);
        return false; 
      }
    }
  }
  return null; 
}

function processAttachmentToJsonGeneric(attachment, config) {
  try {
    const rawCsvString = attachment.getDataAsString();
    const csvData = Utilities.parseCsv(rawCsvString);

    if (csvData.length <= 1) { 
      console.warn(`      CSV data empty or only headers for attachment: "${attachment.getName()}". Skipping conversion.`);
      return null;
    }

    const headers = csvData.shift().map(header => standardizeFieldName(header, config.fieldMap));
    const jsonData = csvData.map((row) => {
      const jsonObj = {};
      headers.forEach((header, colIndex) => {
        jsonObj[header] = handleEmptyValues(row[colIndex], config.timestampFields.includes(header), config.integerFields.includes(header));
      });
      return JSON.stringify(jsonObj);
    });

    const jsonString = jsonData.join("\n");
    const fileName = attachment.getName().replace(/\.[^/.]+$/, "") + "_converted.json";
    const file = DriveApp.getFolderById(folderId).createFile(fileName, jsonString);

    return file.getId();
  } catch (error) {
    console.error(`    Error converting attachment "${attachment ? attachment.getName() : 'unknown'}" to JSON:`, error.message);
    throw error; 
  }
}

function handleEmptyValues(value, isTimestamp, isInteger) {
  if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
    return null;
  }

  const trimmedValue = value.trim();

  if (isTimestamp) {
    let year, month, day, hour, minute, second = '00';
    let match = trimmedValue.match(/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})$/); 
    if (match) {
      day = match[1]; month = match[2]; year = match[3]; hour = match[4]; minute = match[5];
    } else {
      match = trimmedValue.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/); 
      if (match) {
        year = match[1]; month = match[2]; day = match[3]; hour = match[4]; minute = match[5]; second = match[6];
      } else {
        match = trimmedValue.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/); 
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

function loadJsonToBigQueryGeneric(jsonFileId, config) {
  try {
    const file = DriveApp.getFileById(jsonFileId);
    const jsonDataBlob = file.getBlob();

    const loadJob = {
      configuration: {
        load: {
          destinationTable: { projectId, datasetId: config.stagingDatasetId, tableId: config.stagingTableId },
          sourceFormat: "NEWLINE_DELIMITED_JSON",
          writeDisposition: "WRITE_TRUNCATE", 
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
    MailApp.sendEmail({ 
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Staging Load Failed for ${config.name}`,
      body: `An error occurred while loading JSON into BigQuery staging table ${config.stagingDatasetId}.${config.stagingTableId}: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    throw error; 
  } finally {
    try { if (jsonFileId) DriveApp.getFileById(jsonFileId).setTrashed(true); }
    catch (cleanUpError) { console.warn(`    Error deleting temporary JSON file ${jsonFileId}:`, cleanUpError.message); }
  }
}

function standardizeFieldName(header, fieldMap) {
  return fieldMap[header.trim()] || header.trim().replace(/\s+/g, "_");
}

function mergeTablesInBigQueryGeneric(config) {
  try {
    const primaryKeys = Array.isArray(config.primaryKeyForMerge) ? config.primaryKeyForMerge : [config.primaryKeyForMerge];
    const onClause = primaryKeys.map(pk => `T.${pk} = H.${pk}`).join(" AND ");

    const updateSetClause = config.allColumns
      .filter(col => !primaryKeys.includes(col)) 
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
    MailApp.sendEmail({ 
      to: errorNotificationEmails,
      subject: `Error in ${scriptName}: BigQuery Merge Operation Failed for ${config.name}`,
      body: `An error occurred while merging tables in BigQuery for ${config.targetDatasetId}.${config.targetTableId}: \n\n${error.message}\n\nStack trace:\n${error.stack}`
    });
    throw error; 
  }
}

function waitForJobCompletion(job) {
  const jobId = job.jobReference.jobId;
  const maxAttempts = 60; 
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

function main() {
  searchForEmailAndAttachments();
}