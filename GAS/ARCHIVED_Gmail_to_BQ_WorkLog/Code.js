// --- GLOBAL VARIABLES ---
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // My Drive > Temp
var subject = 'Automated Datapipe - WorkLog'; // Subject of the email to search for
var sender = 'noreply-bmchelix@onbmc.com'; // Email address of the sender
var label = 'Dashboard/AutoReports'; // Label applied to the email
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'Remedy'; // Your BigQuery dataset ID
var tableId = 'WorkLog';   // Your BigQuery table ID
var archivedLabel = 'ArchivedReports'; // Add this line for archiving


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
      // Process each attachment (download and upload to BigQuery)
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


// Function to process an attachment (download to Drive and upload to BigQuery)
function processAttachment(attachment) {
  try {
    // Download the attachment content
    var blob = attachment.copyBlob(); 

    // Get the folder 
    var folder = DriveApp.getFolderById(folderId);

    // Create the file in Drive using the blob
    var file = folder.createFile(blob.setName(attachment.getName())); 

    console.log('File created:', file);

    if (file && file.getName()) {
      console.log('  - Attachment saved to Drive:', file.getName()); 

      if (file.getMimeType() === MimeType.CSV) {
        var csvBlob = file.getBlob();
        var csvData = Utilities.parseCsv(csvBlob.getDataAsString());

        // --- Basic Validation: Check if the first row looks like a header ---
        if (csvData.length > 0 && csvData[0].length > 1) { // Check if there are at least two columns
          // 2. Remove the header row
          csvData.shift(); 

          // 3. Convert the filtered data back to CSV string
          var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

          // 4. Upload to BigQuery using WRITE_APPEND
          var job = {
            configuration: {
              load: {
                destinationTable: {
                  projectId: projectId,
                  datasetId: datasetId,
                  tableId: tableId,
                },
                sourceFormat: 'CSV',
                skipLeadingRows: 0, 
                writeDisposition: 'WRITE_APPEND', 
                allowQuotedNewlines: true, 
              },
            },
          };

          // Create a new Blob from the processed content
          var processedCsvBlob = Utilities.newBlob(processedCsvContent, 'application/octet-stream');
          BigQuery.Jobs.insert(job, projectId, processedCsvBlob);

          // Delete the file after the load attempt
          if (file && file.getName()) {
            file.setTrashed(true);
            console.log('  - File', file.getName(), 'deleted from Drive.');
          } else {
            console.warn("Could not delete file. It might not exist anymore.");
          }


          console.log('  - Data from', file.getName(), 'appended to BigQuery.');
        } else {
          console.warn('  - Attachment', file.getName(), 'does not seem to have a valid CSV header. Skipping.');
        }

      } else {
        console.warn('  - Attachment', file.getName(), 'is not a CSV file. Skipping BigQuery upload.'); 
      }
    } else {
      console.error("Error creating file or file doesn't have getName method: ", file);
    }

  } catch (error) {
    console.error('  - Error processing file:', attachment ? attachment.getName() : 'unknown', error); 
  }
}


/*
function createTriggers() {
  // Get all existing triggers
  var allTriggers = ScriptApp.getProjectTriggers();

  // Remove existing triggers for the function
  for (var i = 0; i < allTriggers.length; i++) {
    if (allTriggers[i].getHandlerFunction() === 'searchForEmailAndAttachments') {
      ScriptApp.deleteTrigger(allTriggers[i]);
    }
  }


  // Create new triggers
  ScriptApp.newTrigger('searchForEmailAndAttachments')
      .timeBased()
      .everyDays(1)
      .atHour(8)
      .nearMinute(15)
      .create();

}


// Call the function to create triggers (if using programmatically)
createTriggers(); 
*/