// --- GLOBAL VARIABLES (Update these as needed) ---
// Email search criteria
var subject = 'Automated Report - Outstanding - Shifts';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports'; // This label is now only used for searching

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'Remedy';
var tableId = 'EscalationSnapshots';

// Google Drive folder details
var sourceFolderId = '1ex-KXiXNjcCI9wgv054TGuoeTMmipKOG';
var archiveFolderId = '1YLYsWAypMK3vDdLO2PZb-OAbsdZpAev3';

// Expected number of columns in the CSV files
var expectedColumnCount = 6;

// Expected file name pattern (including extension)
var expectedFileNamePattern = "Escalation.*\.csv";

// Error Notification Emails
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';


// --- FUNCTIONS ---

function processEmailsAndAttachments() {
  // Build the search query - Include is:unread
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label + ' is:unread';

  var threads = GmailApp.search(searchQuery);
  console.log("Number of unread threads found:", threads.length);

  if (threads.length === 0) {
    console.log("No unread emails found.");
    return; // Exit early if no unread emails
  }

  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var messages = thread.getMessages();
    console.log(`Processing thread ID: ${thread.getId()}, Subject: ${thread.getFirstMessageSubject()}, Thread Last Message Date: ${thread.getLastMessageDate()}`);

    for (var j = 0; j < messages.length; j++) {
      var message = messages[j];
      if (message.isUnread()) {
        console.log(`  Processing message ID: ${message.getId()}, Message Date: ${message.getDate()}, From: ${message.getFrom()}`);
        try {
          processMessageAttachments(message);
          message.markRead(); // Mark as read AFTER successful processing
          console.log("Email marked as read after successful processing.");
        } catch (error) {
          console.error("Error processing message:", error);
          console.error(error.stack);
          sendEmailNotification(error, `Error processing message ${j + 1} in thread ${i + 1}`);
        }
      } else {
        console.log('  Message already read. Skipping.');
      }
    }
  }
}


function processMessageAttachments(message) {
  var attachments = message.getAttachments();
  for (var i = 0; i < attachments.length; i++) {
    var attachment = attachments[i];
    var attachmentName = attachment.getName();

    console.log('    Processing attachment:', attachmentName);

    if (attachmentName.match(expectedFileNamePattern)) {
      try {
        var sourceFolder = DriveApp.getFolderById(sourceFolderId);
        var csvFile = sourceFolder.createFile(attachment.copyBlob());
        console.log('      Downloaded attachment:', csvFile.getName());
        processCsvFile(csvFile);
      } catch (error) {
        console.error("Error downloading or processing attachment:", error);
        console.error(error.stack);
        sendEmailNotification(error, `Error downloading or processing attachment ${attachmentName}`);
      }
    } else {
      console.log('    Attachment name does not match the pattern. Skipping.');
    }
  }
}

function processCsvFile(csvFile) {
  try {
    console.log('Processing CSV file:', csvFile.getName());
    var csvContent = csvFile.getBlob().getDataAsString();
    console.log("RAW CSV CONTENT:\n", csvContent); //Added for debugging

    var csvData = Utilities.parseCsv(csvContent);
    console.log("CSV DATA (AFTER PARSING):\n", csvData); //Added for debugging
    console.log("ROW LENGTHS (AFTER PARSING):\n", csvData.map(row => row.length)); //Added for debugging

    csvData.shift(); // Remove header row
    csvData = csvData.filter(row => row.some(cell => cell !== '')); // Remove empty rows
    console.log("CSV DATA (AFTER FILTERING):\n", csvData); //Added for debugging
    console.log("ROW LENGTHS (AFTER FILTERING):\n", csvData.map(row => row.length)); //Added for debugging


    //Check for column count mismatch and add empty columns if needed
    for (let i = 0; i < csvData.length; i++) {
      if (csvData[i].length < expectedColumnCount) {
        csvData[i].push(''); // Add empty column if needed
        console.log('Added empty column to row ' + (i + 1));
      } else if (csvData[i].length > expectedColumnCount) {
        console.error("Error: Row " + (i + 1) + " has too many columns.");
        throw new Error("CSV data has an unexpected number of columns in row " + (i+1)); //Explicitly throw error
      }
    }

    // Process all cells: Remove line breaks, THEN truncate
    csvData = csvData.map(row => row.map(cell => cell ? cell.replace(/[\r\n]+/g, '').substring(0, 100) : ''));

    var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

    // Insert CSV data directly into BigQuery
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
    console.log("CSV data updated in BigQuery table successfully!");

    // Move the original CSV to the archive folder
    moveCsvToArchive(csvFile.getName(), sourceFolderId, archiveFolderId);

    // Delete the original CSV file from Google Drive
    csvFile.setTrashed(true); 

  } catch (error) {
    console.error("Error processing CSV file:", error);
    console.error(error.stack);
    sendEmailNotification(error, `Error processing CSV file ${csvFile.getName()}`);
  }
}


function moveCsvToArchive(fileName, sourceFolderId, archiveFolderId) {
  try {
    var sourceFolder = DriveApp.getFolderById(sourceFolderId);
    var archiveFolder = DriveApp.getFolderById(archiveFolderId);
    var file = sourceFolder.getFilesByName(fileName);
    if (file.hasNext()) {
      file.next().moveTo(archiveFolder);
      console.log("CSV file moved to archive folder.");
    } else {
      console.log("CSV file not found in source folder.");
    }
  } catch (error) {
    console.error("Error moving CSV file to archive:", error);
    console.error(error.stack);
    sendEmailNotification(error, `Error moving CSV file ${fileName} to archive`);
  }
}

function sendEmailNotification(error, message) {
  MailApp.sendEmail({
    to: errorNotificationEmails,
    subject: 'Error in Automated Script',
    body: `An error occurred: ${message}\n\nError details:\n${error.message}\n\nStack trace:\n${error.stack}`
  });
}


function createTrigger() {
  // Clear existing triggers (optional but recommended)
  clearExistingTriggers('processEmailsAndAttachments');

  // Create triggers - Adjust times as needed
  ScriptApp.newTrigger('processEmailsAndAttachments')
      .timeBased()
      .atHour(7).nearMinute(15)
      .everyDays(1)
      .create();
  console.log('Trigger created for 7:15 AM');

  ScriptApp.newTrigger('processEmailsAndAttachments')
      .timeBased()
      .atHour(15).nearMinute(15)
      .everyDays(1)
      .create();
  console.log('Trigger created for 3:15 PM');

  ScriptApp.newTrigger('processEmailsAndAttachments')
      .timeBased()
      .atHour(23).nearMinute(15)
      .everyDays(1)
      .create();
  console.log('Trigger created for 11:15 PM');
}

function clearExistingTriggers(functionName) {
  const existingTriggers = ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === functionName);
  existingTriggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));
  console.log('Cleared existing triggers for ' + functionName);
}