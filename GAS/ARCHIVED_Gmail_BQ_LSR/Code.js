var subject = 'Automated Datapipe - LSR';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'Remedy'; // Your BigQuery dataset ID
var tableId = 'LSR'; // Your BigQuery table ID
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // My Drive > Temp
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';
var expectedColumnCount = 15; // Number of columns expected in the CSV file
var archivedLabel = 'ArchivedReports'; // Add this line


function searchForEmailAndAttachments() {
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label;

  // Search Gmail for matching emails
  var threads = GmailApp.search(searchQuery);

  console.log("Number of emails found:", threads.length);

  // Sort threads by last modified date (descending order)
  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  // Find the latest thread
  var latestThread = threads[0]; // Now the first element is the latest
  console.log('Latest Email Thread:');
  console.log('  Subject:', latestThread.getFirstMessageSubject());

  // Get the latest message from the latest thread
  var messages = latestThread.getMessages();
  var latestMessage = messages[messages.length - 1];

  // Find and process attachments in the latest message
  var attachments = latestMessage.getAttachments();

  console.log('  Number of attachments:', attachments.length);

  if (attachments.length > 0) {
    console.log('  Attachment names:');
    for (var j = 0; j < attachments.length; j++) {
      console.log('    ' + attachments[j].getName());
      // Process each attachment
      processAttachment(attachments[j]);
    }

    // Add label handling AFTER processing attachments
    var archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);
    var dashboardLabelObj = GmailApp.getUserLabelByName(label);

    // Remove the 'dashboard-autoreports' label (using GmailLabel object)
    if (dashboardLabelObj) { 
        latestThread.removeLabel(dashboardLabelObj);
        console.log('Label "' + label + '" removed from email thread.');
    } else {
        console.log('Label "' + label + '" not found.');
    }

    // Add the 'ArchivedReports' label (using GmailLabel object)
    if (archivedLabelObj) { 
        latestThread.addLabel(archivedLabelObj);
        console.log('Label "' + archivedLabel + '" added to email thread.');
    } else {
        console.log('Label "' + archivedLabel + '" not found.');
    }

  } else {
    console.log('  No attachments found.');
  }
}

function processAttachment(attachment) {
  try {
    if (attachment) {
      // 1. Read CSV data
      var csvData = Utilities.parseCsv(attachment.getDataAsString());
      csvData.shift(); // Remove header row
      csvData = csvData.filter(row => row.some(cell => cell !== '')); // Remove empty rows

      // 2. Check for column count mismatch
      for (let i = 0; i < csvData.length; i++) {
        if (csvData[i].length !== expectedColumnCount) {
          console.error("Error: Row " + (i + 1) + " has incorrect number of columns.");
        }
      }

      // 3. Convert the processed CSV data back to a string 
      var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

      // 4. Save the processed CSV to Google Drive (with _amended suffix)
      var originalFileName = attachment.getName();
      var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv'; 
      var file = DriveApp.getFolderById(folderId).createFile(fileName, processedCsvContent);

      console.log('Processed CSV file saved to Google Drive:', file.getUrl());

      // Move csvContent outside the try...catch block
      var csvContent = processedCsvContent; // Assign the processed content to csvContent

      // 5. Insert CSV data directly into BigQuery 
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
            writeDisposition: 'WRITE_TRUNCATE' // This setting deletes the entire table before loading new data
          }
        }
      };
      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(csvContent));

      console.log("CSV data updated in BigQuery table successfully!");

      // 6. Delete the amended CSV file from Google Drive
      deleteCsvFile(fileName, folderId);

    } else {
      console.log("No attachment found in this email.");
    }
  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack);
    // Send email notification
    MailApp.sendEmail({
      to: errorNotificationEmails, // Now sending to multiple addresses
      subject: 'Error in Automated Script',
      body: 'An error occurred while processing the attachment: \n\n' + error.message + '\n\n' + error.stack
    });
  }
}

// Helper function to delete CSV files from Google Drive
function deleteCsvFile(fileName, folderId) {
  var folder = DriveApp.getFolderById(folderId);
  var amendedFile = folder.getFilesByName(fileName);
  if (amendedFile.hasNext()) {
    amendedFile.next().setTrashed(true);
    console.log("Amended CSV file deleted from Google Drive.");
  } else {
    console.log("Amended CSV file not found.");
  }
}

// Function to set up the daily trigger
function createTrigger() {
  // 1. Clear all existing triggers for "searchForEmailAndAttachments"
  const existingTriggers = ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === 'searchForEmailAndAttachments');
  existingTriggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));

  // 2. Create a new daily trigger at 00:10
  ScriptApp.newTrigger('searchForEmailAndAttachments')
      .timeBased()
      .atHour(8)
      .nearMinute(30)
      .everyDays(1)
      .create();

  console.log('Daily trigger created successfully!');
}

// Run this function to create the trigger
createTrigger(); 