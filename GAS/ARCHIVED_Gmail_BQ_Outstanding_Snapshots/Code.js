// --- GLOBAL VARIABLES (Update these as needed) ---
// Email search criteria
var subject = 'Automated Report - Outstanding - Shifts';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'outstanding_snapshots'; // Your BigQuery dataset ID
var tableId = 'snapshots'; // Your BigQuery table ID

// Google Drive folder details
var sourceFolderId = '1ex-KXiXNjcCI9wgv054TGuoeTMmipKOG'; // My Drive > BMC Dashboard > Outstanding
var archiveFolderId = '1YLYsWAypMK3vDdLO2PZb-OAbsdZpAev3'; // My Drive > BMC Dashboard > Outstanding > Archive

// Expected number of columns in the CSV files
var expectedColumnCount = 9; // Adjust this to match your actual CSV files

// Expected file name pattern (including extension)
var expectedFileNamePattern = "OutstandingSnapshots.*\.csv";

// Error Notification Emails
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.org.slack.com';


// --- FUNCTIONS ---

function processEmailsAndAttachments() {
  // Build the search query - Include is:unread
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label + ' is:unread';

  // Search Gmail for matching emails
  var threads = GmailApp.search(searchQuery);

  console.log("Number of threads found:", threads.length);

  // Process each thread
  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var messages = thread.getMessages();

    console.log('Email Thread:', i + 1);
    console.log('  Subject:', thread.getFirstMessageSubject());

    // Iterate through ALL messages in the thread
    for (var j = 0; j < messages.length; j++) {
      var message = messages[j];
      if (message.isUnread()) {
        console.log('  Processing unread message:', j + 1);
        var attachments = message.getAttachments();
        for (var k = 0; k < attachments.length; k++) {
          var attachment = attachments[k];
          var attachmentName = attachment.getName();

          console.log('    Processing attachment:', attachmentName);

          // Check if the attachment name matches the pattern
          if (attachmentName.match(expectedFileNamePattern)) {
            // Download the attachment to the source folder
            var sourceFolder = DriveApp.getFolderById(sourceFolderId);
            var csvFile = sourceFolder.createFile(attachment.copyBlob());
            console.log('      Downloaded attachment:', csvFile.getName());

            // Process the downloaded CSV file
            processCsvFile(csvFile, message); // Pass the message object
          } else {
            console.log('    Attachment name does not match the pattern. Skipping.');
          }
        }
      } else {
        console.log('  Message already read. Skipping.');
      }
    }
  }
}

// Function to process a CSV file
function processCsvFile(csvFile, message) {
  try {
    console.log('Processing CSV file:', csvFile.getName());

    var csvContent = csvFile.getBlob().getDataAsString();
    console.log('CSV content:', csvContent);

    // 2. Check for column count mismatch AND add commas to empty description columns
    var csvData = Utilities.parseCsv(csvContent);
    csvData.shift(); // Remove header row
    csvData = csvData.filter(row => row.some(cell => cell !== '')); // Remove empty rows
    for (let i = 0; i < csvData.length; i++) {
      if (csvData[i].length < expectedColumnCount) {
        csvData[i].push('');
        console.log('Added empty description column to row ' + (i + 1));
      } else if (csvData[i].length > expectedColumnCount) {
        console.error("Error: Row " + (i + 1) + " has too many columns.");
      }
    }

    // *** Process all cells: Remove line breaks, THEN truncate ***
    csvData = csvData.map(row => {
      return row.map((cell, columnIndex) => {
        if (cell) {
          cell = cell.replace(/[\r\n]+/g, '');
          cell = cell.substring(0, 100);
        }
        if (columnIndex === 7) {
          cell = cell.replace(/,/g, '');
        }
        return cell;
      });
    });

    // 3. Convert the processed CSV data back to a string
    var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

    // 4. Save the processed CSV to Google Drive (with _amended suffix)
    var originalFileName = csvFile.getName();
    var fileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv';
    var file = DriveApp.getFolderById(sourceFolderId).createFile(fileName, processedCsvContent);

    console.log('Processed CSV file saved to Google Drive:', file.getUrl());

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
          writeDisposition: 'WRITE_APPEND',
          allow_quoted_newlines: true
        }
      }
    };

    BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(processedCsvContent));

    console.log("CSV data updated in BigQuery table successfully!");

    // Mark the message as read AFTER successful processing
    message.markRead();
    console.log("Email marked as read after successful processing.");

    // 6. Move the original CSV to the archive folder
    moveCsvToArchive(originalFileName, sourceFolderId, archiveFolderId);

    // 7. Delete the amended CSV file from Google Drive
    deleteCsvFile(fileName, sourceFolderId);

  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack);

    // Send error notification email
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: 'Error in Automated Script',
      body: 'An error occurred while processing the attachment: \n\n' + error.message + '\n\n' + error.stack
    });
  }
}

// Helper function to move CSV files to the archive folder
function moveCsvToArchive(fileName, sourceFolderId, archiveFolderId) {
  var sourceFolder = DriveApp.getFolderById(sourceFolderId);
  var archiveFolder = DriveApp.getFolderById(archiveFolderId);

  var originalFile = sourceFolder.getFilesByName(fileName);
  if (originalFile.hasNext()) {
    var fileToMove = originalFile.next();
    fileToMove.moveTo(archiveFolder);
    console.log("Original CSV file moved to archive folder.");
  } else {
    console.log("Original CSV file not found in source folder.");
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