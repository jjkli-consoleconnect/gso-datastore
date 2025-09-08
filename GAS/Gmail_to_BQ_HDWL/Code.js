var scriptName = "Automated Datapipe - HelpDeskAllNOC_and_Worklog";
var subject = "BQ - GSO.HDWL";
var sender = "noreply-bmchelix@onbmc.com";
var label = "CloudWatch";
var projectId = "pccw-internal-virt-agent-uat";
var folderId = "1-CN9TVdXLQlG033djKVG5slzbhADbpdA"; // Make sure this Folder ID is correct and accessible
var errorNotificationEmails = "jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconsole.org.slack.com";
var archivedLabel = "ArchivedReports"; // Make sure this Gmail Label exists
// Centralized PipelineRuns logging
var pipelineRunsDatasetId = 'GSO';
var pipelineRunsTableId = 'PipelineRuns';
var currentRunId = null; // Set in main()

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
      "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy",
      "Product_Family", "ProductDescription" // <-- Removed ExtractedDescription from here
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
      "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRno": "SRno", "ReportedBy": "ReportedBy",
      "Product Family": "Product_Family", // <-- Add mapping
      "ProductDescription": "ProductDescription" // <-- Add mapping
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
      "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By", "ExtractedDescription" // <-- Added here
    ],
    primaryKeyForMerge: "WorkLog_ID",
    fieldMap: {
      "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
      "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
      "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
      "LastModifiedBy": "Last_Modified_By",
      "ExtractedDescription": "ExtractedDescription" // <-- Added here
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
    // Log completion with 0 rows if we had a RUNNING entry
    if (currentRunId) {
      logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'No matching emails. Nothing to do.', null, null, 0, null, null);
    }
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
  // Final SUCCESS log with rows merged = total CSVs loaded
  if (currentRunId) {
    logPipelineRun(scriptName, currentRunId, 'SUCCESS', 'INFO', 'Data pipeline run complete.', null, null, totalAttachmentsLoadedToBigQuery, null, null);
  }
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
    // Log attachment metadata to help diagnose parsing issues
    try {
      const blob = attachment.copyBlob ? attachment.copyBlob() : attachment.getAs ? attachment.getAs('application/octet-stream') : null;
      const size = blob ? blob.getBytes().length : (attachment.getSize ? attachment.getSize() : 'unknown');
      const contentType = blob ? blob.getContentType() : (attachment.getContentType ? attachment.getContentType() : 'unknown');
      console.log(`      Attachment metadata: name="${attachment.getName()}", size=${size}, contentType=${contentType}`);
    } catch (metaErr) {
      console.log(`      Attachment metadata logging failed: ${metaErr.message}`);
    }

    // Quick-detect upstream error payloads (JSON error responses) and skip them
    try {
      const previewRaw = attachment.getDataAsString();
      const preview = (typeof previewRaw === 'string') ? previewRaw.trim() : '';
      if (preview && (preview[0] === '{' || preview[0] === '[')) {
        try {
          const parsed = JSON.parse(preview);
          if (parsed && (parsed.statusCode || parsed.error || parsed.message)) {
            console.log(`      Attachment appears to be an upstream error payload: ${attachment.getName()}`);
            try {
              MailApp.sendEmail({
                to: errorNotificationEmails,
                subject: `Upstream error payload received for ${scriptName}: ${attachment.getName()}`,
                body: `Detected an upstream error payload attached to an incoming email for pipeline ${scriptName}.

Attachment: ${attachment.getName()}
Config: ${config.name}

Preview:
${preview}
`
              });
            } catch (mailErr) {
              console.log('      Failed to send notification email for error payload: ' + mailErr.message);
            }
            // Treat as no-data so caller will mark message read and continue
            return null;
          }
        } catch (jsonErr) {
          // Not valid JSON, continue to parsing attempts
        }
      }
    } catch (previewErr) {
      console.log('      Could not read attachment preview for quick error-detect: ' + previewErr.message);
    }

    // Use a tolerant CSV parser that attempts multiple encodings and delimiters
    const csvData = robustParseCsv(attachment);

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
    if (currentRunId) {
      logPipelineRun(scriptName, currentRunId, 'ERROR', 'ERROR', 'Error loading data: ' + error.message, null, null, null, null, null);
    }
    throw error; 
  } finally {
    try { if (jsonFileId) DriveApp.getFileById(jsonFileId).setTrashed(true); }
    catch (cleanUpError) { console.warn(`    Error deleting temporary JSON file ${jsonFileId}:`, cleanUpError.message); }
  }
}

function standardizeFieldName(header, fieldMap) {
  return fieldMap[header.trim()] || header.trim().replace(/\s+/g, "_");
}

/**
 * Robust CSV parsing: tries different encodings, strips BOM, normalizes line endings,
 * and attempts common delimiters (comma, semicolon, tab). Returns array of rows (arrays).
 * Throws an Error if parsing fails after heuristics.
 */
function robustParseCsv(attachment) {
  // Try default Apps Script string extraction first
  let raw = null;
  let errors = [];

  try {
    raw = attachment.getDataAsString();
    raw = stripBOM(raw);
    const attempt = tryParseWithDelimiter(raw);
    if (attempt) return attempt;
  } catch (e) {
    errors.push('getDataAsString default failed: ' + e.message);
  }

  // Try reading as UTF-8 by getting bytes and decoding with Utilities
  try {
    const bytes = attachment.getBytes();
    // Apps Script doesn't expose direct encoding conversions; try constructing string from bytes
    raw = String.fromCharCode.apply(null, bytes);
    raw = stripBOM(raw);
    const attempt = tryParseWithDelimiter(raw);
    if (attempt) return attempt;
  } catch (e) {
    errors.push('byte->string attempt failed: ' + e.message);
  }

  // Attempt UTF-16 (LE/BE) decoding if bytes show UTF-16 characteristics
  try {
    const bytes = attachment.getBytes();
    if (detectLikelyUtf16(bytes)) {
      console.log('    Detected likely UTF-16 encoding; attempting UTF-16 LE/BE decode.');
      try {
        const le = decodeUtf16LE(bytes);
        const attemptLE = tryParseWithDelimiter(stripBOM(le));
        if (attemptLE) return attemptLE;
      } catch (e) {
        errors.push('utf16le_failed:' + e.message);
      }
      try {
        const be = decodeUtf16BE(bytes);
        const attemptBE = tryParseWithDelimiter(stripBOM(be));
        if (attemptBE) return attemptBE;
      } catch (e) {
        errors.push('utf16be_failed:' + e.message);
      }
    }
  } catch (e) {
    errors.push('utf16_detection_failed:' + e.message);
  }

  // As a last resort, try trimming lines and replacing stray nulls then parse
  try {
    if (raw === null) raw = attachment.getDataAsString();
    raw = raw.replace(/\u0000/g, '');
    raw = raw.replace(/\r\n?/g, '\n');
    raw = stripBOM(raw);
    const attempt = tryParseWithDelimiter(raw);
    if (attempt) return attempt;
  } catch (e) {
    errors.push('final normalized attempt failed: ' + e.message);
  }

  // If we reach here, all attempts failed. Build informative error and throw.
  // Attempt to save diagnostic artifacts (preview + binary snippet) to Drive for inspection
  try {
    const folder = DriveApp.getFolderById(folderId);
    try {
      const previewText = (raw && typeof raw === 'string') ? raw.substring(0, 2000) : (attachment.getDataAsString ? attachment.getDataAsString().substring(0, 2000) : 'no-preview-available');
      const previewFile = folder.createFile(attachment.getName() + '_preview.txt', previewText);
      errors.push('preview_file_id:' + previewFile.getId());

      // Attempt to find likely incident numbers in the preview to speed up manual triage
      try {
        const likely = extractLikelyIncidentNumbers(previewText);
        if (likely && likely.length > 0) {
          errors.push('likely_incidents_preview:' + likely.slice(0, 10).join(','));
          console.log('    Likely incidents in preview: ' + likely.slice(0, 10).join(', '));
        }
      } catch (e) {
        // non-fatal
      }
    } catch (diagErr) {
      errors.push('diag_preview_failed:' + diagErr.message);
    }

    try {
      const bytes = attachment.getBytes();
      const slice = bytes.slice(0, 200000); // first ~200KB
      const blob = Utilities.newBlob(slice, attachment.getContentType ? attachment.getContentType() : 'application/octet-stream', attachment.getName() + '_raw_part.bin');
      const rawFile = folder.createFile(blob);
      errors.push('raw_file_id:' + rawFile.getId());
      try {
        // also try to decode the binary snippet as UTF-16/UTF-8 to search for incident numbers
        var decoded = null;
        try { decoded = (typeof raw === 'string' ? raw : attachment.getDataAsString()); } catch(e) { decoded = null; }
        if (!decoded) {
          try { decoded = String.fromCharCode.apply(null, slice); } catch(e) { decoded = null; }
        }
        if (decoded) {
          const likelyRaw = extractLikelyIncidentNumbers(decoded);
          if (likelyRaw && likelyRaw.length > 0) {
            errors.push('likely_incidents_raw:' + likelyRaw.slice(0, 10).join(','));
            console.log('    Likely incidents in raw snippet: ' + likelyRaw.slice(0, 10).join(', '));
          }
        }
      } catch (e) {
        // ignore
      }
    } catch (diagErr) {
      errors.push('diag_raw_dump_failed:' + diagErr.message);
    }
  } catch (e) {
    // If Drive diagnostic creation fails, include that in errors but continue to throw below
    errors.push('diag_folder_access_failed:' + e.message);
  }

  const errMsg = 'Could not parse CSV attachment "' + (attachment ? attachment.getName() : 'unknown') + '" after multiple attempts. Details: ' + errors.join(' | ');
  throw new Error(errMsg);
}

function tryParseWithDelimiter(rawString) {
  if (!rawString || typeof rawString !== 'string') return null;
  // Normalize line endings
  rawString = rawString.replace(/\r\n?/g, '\n');
  // Common delimiters to try in order
  const delimiters = [',', ';', '\t'];

  for (const delim of delimiters) {
    try {
      // Utilities.parseCsv supports delimiter as second arg when called on a single line.
      // We will split into lines and parse each line with the delimiter to avoid CSV quirks,
      // but first try the simple Utilities.parseCsv on entire text (it handles newlines).
      const parsed = Utilities.parseCsv(rawString);
      // Basic sanity checks: at least 2 rows and header values non-empty
      if (parsed && parsed.length > 1 && parsed[0].some(h => h && h.toString().trim() !== '')) {
        return parsed;
      }

      // Fall back: try splitting lines and parsing line-by-line using delimiter
      const lines = rawString.split('\n').filter(Boolean);
      if (lines.length === 0) continue;
      const parsedLines = lines.map(line => line.split(delim).map(cell => cell));
      // Ensure header row exists and has non-empty cells
      if (parsedLines[0].some(h => h && h.toString().trim() !== '')) {
        return parsedLines;
      }
    } catch (e) {
      // ignore and try next delimiter
    }
  }
  return null;
}

function stripBOM(s) {
  if (!s || typeof s !== 'string') return s;
  return s.replace(/^\uFEFF/, '');
}

// Heuristic: check for null bytes in every other byte which often indicates UTF-16
function detectLikelyUtf16(bytes) {
  if (!bytes || bytes.length < 2) return false;
  let zeroCountLE = 0;
  let zeroCountBE = 0;
  const checkLen = Math.min(bytes.length, 200);
  for (let i = 0; i < checkLen - 1; i += 2) {
    if (bytes[i] === 0) zeroCountBE++;
    if (bytes[i + 1] === 0) zeroCountLE++;
  }
  // If a significant fraction of even or odd bytes are zero, likely UTF-16
  return (zeroCountLE / (checkLen / 2) > 0.6) || (zeroCountBE / (checkLen / 2) > 0.6);
}

function decodeUtf16LE(bytes) {
  // bytes is an array of numbers 0-255. Convert pairs to code units (little-endian).
  const codeUnits = [];
  for (let i = 0; i < bytes.length - 1; i += 2) {
    codeUnits.push(bytes[i] | (bytes[i + 1] << 8));
  }
  return String.fromCharCode.apply(null, codeUnits);
}

function decodeUtf16BE(bytes) {
  const codeUnits = [];
  for (let i = 0; i < bytes.length - 1; i += 2) {
    codeUnits.push((bytes[i] << 8) | bytes[i + 1]);
  }
  return String.fromCharCode.apply(null, codeUnits);
}

function extractLikelyIncidentNumbers(text) {
  if (!text || typeof text !== 'string') return [];
  const candidates = {};
  // Common patterns: sequences of 6-12 digits, or SR/no formats like SR12345
  const digitRe = /\b(\d{6,12})\b/g;
  let m;
  while ((m = digitRe.exec(text)) !== null) {
    candidates[m[1]] = (candidates[m[1]] || 0) + 1;
  }
  // SR or SRno prefixes
  const srRe = /\b(?:SR|SRno|SRNo|SR#)\s*[:#-]?\s*(\d{4,12})\b/g;
  while ((m = srRe.exec(text)) !== null) {
    candidates[m[1]] = (candidates[m[1]] || 0) + 2; // boost
  }
  // Turn into sorted list by frequency
  const sorted = Object.keys(candidates).sort((a, b) => candidates[b] - candidates[a]);
  return sorted;
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
    // Best-effort wait, but do not throw if it fails
    waitForJobCompletion(job);
  } catch (e) {
    // Swallow logging errors to avoid breaking main flow
    console.warn('logPipelineRun failed: ' + e.message);
  }
}

function escapeSqlLiteral(s) {
  return s.replace(/'/g, "''");
}



function main() {
  currentRunId = Utilities.getUuid();
  logPipelineRun(scriptName, currentRunId, 'RUNNING', 'INFO', 'Pipeline run started', null, null, null, null, null);
  searchForEmailAndAttachments();
}