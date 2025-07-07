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
            if (!await processMessageAttachments(message)) {
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

  for (var i = 0; i < attachments.length; i++) {
    var attachment = attachments[i];
    var attachmentName = attachment.getName();

    console.log('    Processing attachment:', attachmentName);

    try {
      var processResult = false;
      if (attachmentName.match(expectedFileNamePattern_Remedy)) {
        processResult = await processAttachment(attachment, 'Remedy', expectedColumnCount_Remedy, datasetId_Remedy, tableId_Remedy);
        expectedAttachmentsProcessed++;
        if (processResult) expectedAttachmentsSucceeded++;

      } else if (attachmentName.match(expectedFileNamePattern_Outstanding)) {
        processResult = await processAttachment(attachment, 'Outstanding', expectedColumnCount_Outstanding, datasetId_Outstanding, tableId_Outstanding);
        expectedAttachmentsProcessed++;
        if (processResult) expectedAttachmentsSucceeded++;
      } else {
        console.log(`      Ignoring unexpected attachment: ${attachmentName}`);
      }
    } catch (error) {
      console.error("Error processing attachment:", error);
      console.error(error.stack);
      sendEmailNotification(error, `Error processing attachment ${attachmentName}`);
    }
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

    var csvData = Utilities.parseCsv(csvContent);
    csvData.shift(); //Remove Header Row

    csvData = csvData.filter(row => row.some(cell => cell !== '')); //Remove Empty Rows

    csvData = csvData.map(row => row.map(cell => cell ? cell.replace(/[\r\n]+/g, '').substring(0, 100) : ''));

    var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

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
          writeDisposition: 'WRITE_APPEND', 
          allow_quoted_newlines: true
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


function sendEmailNotification(error, message) {
  MailApp.sendEmail({
    to: errorNotificationEmails,
    subject: 'Error in Automated Script',
    body: `An error occurred: ${message}\n\nError details:\n${error.message}\n\nStack trace:\n${error.stack}`
  });
}

