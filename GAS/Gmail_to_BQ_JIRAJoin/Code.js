// --- GLOBAL VARIABLES (Update these for each table) ---
// Email search criteria
var subject = 'Automated Datapipe - JIRAJoin';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'RemedyICS'; // Your BigQuery dataset ID
var tableId = 'JIRAJoin'; // Your BigQuery table ID

// Google Drive folder details
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // Your Google Drive folder ID

// CSV data specifics
var expectedColumnCount = 6; // Expected number of columns in your CSV data

// Error Notification Emails
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';

// Archive Label
var archivedLabel = 'ArchivedReports'; // Name of your archive label


// --- FUNCTIONS ---
function searchForEmailAndAttachments() {
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label;
  var threads = GmailApp.search(searchQuery);
  console.log("Number of emails found:", threads.length);

  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  var latestThread = threads[0];
  console.log('Latest Email Thread:');
  console.log('  Subject:', latestThread.getFirstMessageSubject());

  var messages = latestThread.getMessages();
  var latestMessage = messages[messages.length - 1];

  var attachments = latestMessage.getAttachments();
  console.log('  Number of attachments:', attachments.length);

  if (attachments.length > 0) {
    console.log('  Attachment names:');
    for (var j = 0; j < attachments.length; j++) {
      console.log('    ' + attachments[j].getName());
      processAttachment(attachments[j]);
    }

    var archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);
    var dashboardLabelObj = GmailApp.getUserLabelByName(label);
    var parentLabelObj = GmailApp.getUserLabelByName('Dashboard');

    console.log('Attempting to remove label:', label);
    console.log('Attempting to remove parent label: Dashboard');
    console.log('Attempting to add label:', archivedLabel);

    if (dashboardLabelObj) {
      latestThread.removeLabel(dashboardLabelObj);
      console.log('Label "' + label + '" removed from email thread.');
    } else {
      console.log('Label "' + label + '" not found.');
    }

    if (parentLabelObj) {
      latestThread.removeLabel(parentLabelObj);
      console.log('Parent label "Dashboard" removed from email thread.');
    } else {
      console.log('Parent label "Dashboard" not found.');
    }

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
      var csvData = Utilities.parseCsv(attachment.getDataAsString());
      csvData.shift();
      csvData = csvData.filter(row => row.some(cell => cell !== ''));

      for (let i = 0; i < csvData.length; i++) {
        if (csvData[i].length !== expectedColumnCount) {
          console.error("Error: Row " + (i + 1) + " has incorrect number of columns.");
        }
      }

      var processedCsvContent = csvData.map(row => row.join(',')).join('\n');
      var originalFileName = attachment.getName();
      var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv';
      var file = DriveApp.getFolderById(folderId).createFile(fileName, processedCsvContent);
      console.log('Processed CSV file saved to Google Drive:', file.getUrl());

      var csvContent = processedCsvContent;

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
            writeDisposition: 'WRITE_TRUNCATE'
          }
        }
      };
      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(csvContent));
      console.log("CSV data updated in BigQuery table successfully!");

      deleteCsvFile(fileName, folderId);
    } else {
      console.log("No attachment found in this email.");
    }
  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack);

    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: 'Error in Automated Script',
      body: 'An error occurred while processing the attachment: \n\n' + error.message + '\n\n' + error.stack
    });
  }
}

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

/*
function createTrigger() {
  const existingTriggers = ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === 'searchForEmailAndAttachments');
  existingTriggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger('searchForEmailAndAttachments')
    .timeBased()
    .atHour(8)
    .nearMinute(15)
    .everyDays(1)
    .create();
  console.log('Daily trigger created successfully!');
}
*/