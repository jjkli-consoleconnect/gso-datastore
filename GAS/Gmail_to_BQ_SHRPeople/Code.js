// --- GLOBAL VARIABLES ---
var subject = 'Automated Datapipe - SHRPeople';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'RemedyICS';
var tableId = 'SHRPeople';

// Google Drive folder details
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA';

// Error notifications
var errorNotificationEmails = 'jjkli@consoleconnect.com,aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';

// Archive Label
var archivedLabel = 'ArchivedReports';

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

    //Label Handling
    var archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);
    var dashboardLabelObj = GmailApp.getUserLabelByName(label);

    if (dashboardLabelObj) {
      latestThread.removeLabel(dashboardLabelObj);
      console.log('Label "' + label + '" removed from email thread.');
    } else {
      console.log('Label "' + label + '" not found.');
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
      csvData.shift(); //remove header row
      csvData = csvData.filter(row => row.some(cell => cell !== '')); //remove empty rows

      //Data Transformation (all columns as strings)
      var transformedData = csvData.map(row => {
        return [
          row[0],  // CustID
          row[1],  // CustName
          row[2],  // SRNo
          row[3],  // Product Family
          row[4],  // SiteA
          row[5],  // SiteB
          row[6],  // Region A
          row[7],  // Region B
          row[8],  // Product ID
          row[9],  // Insight Circuit ID
          row[10]  // Circuit Owner
        ];
      });

      // Convert back to CSV string
      var processedCsvContent = transformedData.map(row => row.join(',')).join('\n');

      // Save to Google Drive (temporary)
      var originalFileName = attachment.getName();
      var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv';
      var file = DriveApp.getFolderById(folderId).createFile(fileName, processedCsvContent);
      console.log('Processed CSV file saved to Google Drive:', file.getUrl());

      // Load to BigQuery
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
      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(processedCsvContent));
      console.log("CSV data updated in BigQuery table successfully!");

      // Delete from Drive
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