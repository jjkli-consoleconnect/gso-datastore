// --- GLOBAL VARIABLES (Update these as needed) ---
// Email search criteria
var subject = 'Automated Datapipe - BQ - Snapshot by Shift';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';

// BigQuery details (for both types of reports)
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId_Remedy = 'Snapshot';       // Dataset for Escalation Snapshots
var tableId_Remedy = 'RemedyEscalationSnapshot';
var datasetId_Outstanding = 'Snapshot'; // Dataset for Outstanding Snapshots
var tableId_Outstanding = 'RemedyOutstandingSnapshot';

// Google Drive folder details
var sourceFolderId = '1ex-KXiXNjcCI9wgv054TGuoeTMmipKOG';
var archiveFolderId = '1YLYsWAypMK3vDdLO2PZb-OAbsdZpAev3';

// Expected number of columns in the CSV files
var expectedColumnCount_Remedy = 6;
var expectedColumnCount_Outstanding = 9;

// Expected file name patterns (including extensions)
var expectedFileNamePattern_Remedy = "Escalation.*\.csv";
var expectedFileNamePattern_Outstanding = "OutstandingSnapshots.*\.csv";

// Error Notification Emails
var errorNotificationEmails = 'jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com';


// --- FUNCTIONS ---

async function processEmailsAndAttachments() {
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label + ' is:unread';

  try {
    var threads = GmailApp.search(searchQuery);
    console.log("Number of unread threads found:", threads.length);

    if (threads.length === 0) {
      console.log("No unread emails found.");
      return;
    }

    for (var i = 0; i < threads.length; i++) {
      var thread = threads[i];
      var messages = thread.getMessages();
      console.log(`Processing thread ID: ${thread.getId()}, Subject: ${thread.getFirstMessageSubject()}, Thread Last Message Date: ${thread.getLastMessageDate()}`);

      var processedSuccessfully = true;

      for (var j = 0; j < messages.length; j++) {
        var message = messages[j];
        if (message.isUnread()) {
          console.log(`  Processing message ID: ${message.getId()}, Message Date: ${message.getDate()}, From: ${message.getFrom()}`);
          try {
            var result = await processMessageAttachments(message);
            if (result === 'SKIP_MESSAGE') {
              // Message contained only error payloads from source - mark it read and continue.
              message.markRead();
              console.log('  Message marked as read (contained only source error payloads).');
            } else if (!result) {
              processedSuccessfully = false;
            }
          } catch (error) {
            console.error("Error processing message:", error);
            console.error(error.stack);
            sendEmailNotification(error, `Error processing message ${j + 1} in thread ${i + 1}`);
            processedSuccessfully = false;
          }
        } else {
          console.log('  Message already read. Skipping.');
        }
      }

      // Mark as read and remove the specified label if all attachments were processed successfully
      if (processedSuccessfully) {
        thread.markRead();
        var dashboardLabelObj = GmailApp.getUserLabelByName(label);
        thread.removeLabel(dashboardLabelObj);
        console.log("Email marked as read and label removed after successful processing.");
      } else {
        console.log("Email NOT marked as read due to errors during attachment processing.");
      }
    }
  } catch (error) {
    console.error("Top-level error:", error);
    console.error(error.stack);
    sendEmailNotification(error, "Top-level error occurred.");
  }
}

async function processMessageAttachments(message) {
  var attachments = message.getAttachments();
  var expectedAttachmentsProcessed = 0;
  var expectedAttachmentsSucceeded = 0;
  var expectedAttachmentsErrorPayloads = 0;

  for (var i = 0; i < attachments.length; i++) {
    var attachment = attachments[i];
    var attachmentName = attachment.getName();

    console.log('    Processing attachment:', attachmentName);

    try {
      var processResult = false;
      if (attachmentName.match(expectedFileNamePattern_Remedy)) {
        processResult = await processAttachment(attachment, 'Remedy', expectedColumnCount_Remedy, datasetId_Remedy, tableId_Remedy);
        expectedAttachmentsProcessed++;
        if (processResult === 'ERROR_PAYLOAD') {
          expectedAttachmentsErrorPayloads++;
        } else if (processResult) {
          expectedAttachmentsSucceeded++;
        }

      } else if (attachmentName.match(expectedFileNamePattern_Outstanding)) {
        processResult = await processAttachment(attachment, 'Outstanding', expectedColumnCount_Outstanding, datasetId_Outstanding, tableId_Outstanding);
        expectedAttachmentsProcessed++;
        if (processResult === 'ERROR_PAYLOAD') {
          expectedAttachmentsErrorPayloads++;
        } else if (processResult) {
          expectedAttachmentsSucceeded++;
        }
      } else {
        console.log(`      Ignoring unexpected attachment: ${attachmentName}`);
      }
    } catch (error) {
      console.error("Error processing attachment:", error);
      console.error(error.stack);
      sendEmailNotification(error, `Error processing attachment ${attachmentName}`);
    }
  }

  // If ALL expected attachments are error payloads from source, skip this message entirely.
  if (expectedAttachmentsProcessed > 0 && expectedAttachmentsProcessed === expectedAttachmentsErrorPayloads) {
    console.log("All expected attachments were source error payloads. Skipping this message.");
    return 'SKIP_MESSAGE';
  }

  //Check overall success - Only mark as read if expected attachments were processed successfully
  var allExpectedAttachmentsProcessedSuccessfully = expectedAttachmentsProcessed > 0 && expectedAttachmentsProcessed === expectedAttachmentsSucceeded;


  if (!allExpectedAttachmentsProcessedSuccessfully) {
      console.log("Expected Attachments Processing Summary:");
      console.log(`  Total Expected Attachments: ${expectedAttachmentsProcessed}`);
      console.log(`  Successfully Processed: ${expectedAttachmentsSucceeded}`);
      console.log(`  Failed to process: ${expectedAttachmentsProcessed-expectedAttachmentsSucceeded}`);
  }
  return allExpectedAttachmentsProcessedSuccessfully;
}

async function processAttachment(attachment, reportType, expectedColumnCount, datasetId, tableId) {
  var sourceFolder = DriveApp.getFolderById(sourceFolderId);
  try {
    var csvFile = sourceFolder.createFile(attachment.copyBlob());
    console.log('      Downloaded attachment:', csvFile.getName());
    var success = await processCsvFile(csvFile, reportType, expectedColumnCount, datasetId, tableId);
    return success; 
  } catch (error) {
    console.error(`Error downloading or processing attachment for ${reportType}:`, error);
    console.error(error.stack);
    sendEmailNotification(error, `Error downloading or processing attachment ${attachment.getName()} for ${reportType}`);
    return false; 
  }
}

async function processCsvFile(csvFile, reportType, expectedColumnCount, datasetId, tableId) {
  try {
    console.log('Processing CSV file:', csvFile.getName());
    var csvContent = csvFile.getBlob().getDataAsString();

    // Detect known non-CSV payloads so failures are explicit in logs/alerts.
    if (/^\s*\{\s*"statusCode"\s*:\s*\d+/i.test(csvContent) && /"error"\s*:\s*"/i.test(csvContent)) {
      console.error('Attachment content is JSON error payload from source, not CSV. File: ' + csvFile.getName() + ' Content: ' + csvContent.substring(0, 200));
      sendEmailNotification(
        new Error('Source system sent error payload instead of CSV'),
        'JSON error payload received instead of CSV for ' + reportType + ': ' + csvFile.getName()
      );
      return 'ERROR_PAYLOAD';
    }

    try {
      ensureTableSchemaIncludesCsvHeaders(csvContent, datasetId, tableId, reportType);
    } catch (schemaError) {
      // Do not block ingestion if header parsing/schema extension fails for a bad file.
      console.warn('Schema merge skipped for ' + reportType + ': ' + schemaError.message);
    }

    // Load raw CSV to preserve quoting/embedded commas/newlines from source.
    var processedCsvContent = csvContent.replace(/^\uFEFF/, '').replace(/\u0000/g, '');
    var skipLeadingRows = 1;

    var job = {
      configuration: {
        load: {
          destinationTable: {
            projectId: projectId,
            datasetId: datasetId,
            tableId: tableId
          },
          sourceFormat: 'CSV',
          skipLeadingRows: skipLeadingRows,
          writeDisposition: 'WRITE_APPEND', 
          allowQuotedNewlines: true,
          allowJaggedRows: true,
          ignoreUnknownValues: true,
          maxBadRecords: 100
        }
      }
    };

    BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(processedCsvContent));
    console.log(`CSV data for ${reportType} updated in BigQuery table successfully!`);
    return true; 

  } catch (error) {
    console.error(`Error processing CSV file for ${reportType}:`, error);
    console.error(error.stack);
    sendEmailNotification(error, `Error processing CSV file ${csvFile.getName()} for ${reportType}`);
    return false; 
  }
}

function ensureTableSchemaIncludesCsvHeaders(csvContent, datasetId, tableId, reportType) {
  var firstLine = csvContent.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/, 1)[0];
  if (!firstLine) {
    throw new Error('CSV appears empty (no header row) for ' + reportType);
  }

  var headerCells = [];
  try {
    headerCells = Utilities.parseCsv(firstLine)[0] || [];
  } catch (headerParseError) {
    // Header line can be malformed in occasional source files; skip schema merge for that file.
    throw new Error('Unable to parse CSV header row for ' + reportType + ': ' + headerParseError.message);
  }
  if (headerCells.length === 0) {
    throw new Error('Unable to read CSV header row for ' + reportType);
  }

  var table = BigQuery.Tables.get(projectId, datasetId, tableId);
  var existingFields = (table.schema && table.schema.fields) ? table.schema.fields : [];
  var existingByLower = {};
  for (var i = 0; i < existingFields.length; i++) {
    existingByLower[existingFields[i].name.toLowerCase()] = true;
  }

  var updatedFields = existingFields.slice();
  var addedFieldNames = [];
  for (var j = 0; j < headerCells.length; j++) {
    var normalized = normalizeBqFieldName(headerCells[j], j + 1);
    if (!existingByLower[normalized.toLowerCase()]) {
      updatedFields.push({
        name: normalized,
        type: 'STRING',
        mode: 'NULLABLE'
      });
      existingByLower[normalized.toLowerCase()] = true;
      addedFieldNames.push(normalized);
    }
  }

  if (addedFieldNames.length > 0) {
    BigQuery.Tables.patch({ schema: { fields: updatedFields } }, projectId, datasetId, tableId);
    console.log('Added new columns for ' + reportType + ': ' + addedFieldNames.join(', '));
  }
}

function normalizeBqFieldName(name, index) {
  var normalized = (name || '').toString().replace(/^\uFEFF/, '').trim().toLowerCase();
  normalized = normalized.replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '');
  if (!normalized) {
    normalized = 'column_' + index;
  }
  if (!/^[a-z_]/.test(normalized)) {
    normalized = 'f_' + normalized;
  }
  return normalized.substring(0, 128);
}


function sendEmailNotification(error, message) {
  MailApp.sendEmail({
    to: errorNotificationEmails,
    subject: 'Error in Automated Script',
    body: `An error occurred: ${message}\n\nError details:\n${error.message}\n\nStack trace:\n${error.stack}`
  });
}

