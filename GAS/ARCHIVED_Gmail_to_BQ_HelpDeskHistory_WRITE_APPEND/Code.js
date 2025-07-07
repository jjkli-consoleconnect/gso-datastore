// --- GLOBAL VARIABLES (Update these for each table) ---
// Email search criteria
var subject = 'Automated Datapipe - HelpDesk';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'Remedy'; // Your BigQuery dataset ID
var tableId = 'HelpDeskHistory'; // Your BigQuery table ID

// Google Drive folder details
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // My Drive > Temp

// Your email addresses for error notifications (comma-separated)
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';

// Archive Label (Add this)
var archivedLabel = 'ArchivedReports'; // Name of your archive label

// --- FUNCTIONS ---
function searchForEmailAndAttachments() {
  // Build the search query
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
      const expectedColumnCount = 24; // Replace with your expected column count
      for (let i = 0; i < csvData.length; i++) {
        if (csvData[i].length !== expectedColumnCount) {
          console.error("Error: Row " + (i + 1) + " has incorrect number of columns.");
          // You can handle the error here (e.g., remove the row or log it)
        }
      }

      // 3. Revamp the last column
      for (let i = 0; i < csvData.length; i++) {
        csvData[i][csvData[i].length - 1] = revampCustomerName(csvData[i][csvData[i].length - 1]);
      }

      // 4. Convert the processed CSV data back to a string 
      var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

      // 5. Save the processed CSV to Google Drive (with _amended suffix)
      var originalFileName = attachment.getName();
      var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv'; // Extract file name and add _amended suffix
      var file = DriveApp.getFolderById(folderId).createFile(fileName, processedCsvContent);

      console.log('Processed CSV file saved to Google Drive:', file.getUrl());

      // Move csvContent outside the try...catch block
      var csvContent = processedCsvContent; // Assign the processed content to csvContent

      // 6. Insert CSV data directly into BigQuery 
      var job = {
        configuration: {
          load: {
            destinationTable: {
              projectId: projectId, // Your project ID
              datasetId: datasetId, // Your dataset ID
              tableId: tableId // Your table ID
            },
            sourceFormat: 'CSV',
            skipLeadingRows: 0,
            writeDisposition: 'WRITE_APPEND' // This setting appends data to the table
          }
        }
      };
      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(csvContent));

      console.log("CSV data appended to BigQuery table successfully!");

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


// Helper function to revamp the customer name field
function revampCustomerName(str) {
  // Convert to lowercase
  str = str.toLowerCase();

  // Replace spaces with hyphens
  str = str.replace(/\s/g, '-');

  // Remove any non-alphanumeric characters and hyphens
  str = str.replace(/[^a-z0-9-]/g, '');

  return str;
}


// Function to set up the daily trigger (Uncomment to use)
/*
function createTrigger() {
  // 1. Clear all existing triggers for "searchForEmailAndAttachments"
  const existingTriggers = ScriptApp.getProjectTriggers().filter(trigger => trigger.getHandlerFunction() === 'searchForEmailAndAttachments');
  existingTriggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));

  // 2. Create a new daily trigger at 00:10
  ScriptApp.newTrigger('searchForEmailAndAttachments')
    .timeBased()
    .atHour(8)
    .nearMinute(10)
    .everyDays(1)
    .create();

  console.log('Daily trigger created successfully!');
}

// Run this function to create the trigger (Uncomment to use)
//createTrigger();
*/