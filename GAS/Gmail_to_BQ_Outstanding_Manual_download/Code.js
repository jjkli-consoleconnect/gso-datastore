// --- GLOBAL VARIABLES (Update these as needed) ---
// Email search criteria
var subject = 'Automated Report - Outstanding - Shifts'; 
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'dashboard-autoreports';

// BigQuery details
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'outstanding_snapshots'; // Your BigQuery dataset ID
var tableId = 'snapshots'; // Your BigQuery table ID

// Google Drive folder details
var sourceFolderId = '1ex-KXiXNjcCI9wgv054TGuoeTMmipKOG'; // My Drive > BMC Dashboard > Outstanding 

// Expected number of columns in the CSV files
var expectedColumnCount = 9; // Adjust this to match your actual CSV files

// Expected file name pattern (including extension)
var expectedFileNamePattern = "OutstandingSnapshots.*\.csv";

// --- FUNCTIONS ---

// Function to process emails and attachments
function processEmailsAndAttachments() {
  // Build the search query
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label;

  // Search Gmail for matching emails
  var threads = GmailApp.search(searchQuery);

  console.log("Number of threads found:", threads.length);

  // Process the latest thread (if any)
  if (threads.length > 0) {
    // Sort threads by last modified date (descending order)
    threads.sort(function(a, b) {
      return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
    });

    var thread = threads[0]; // Get the latest thread
    var messages = thread.getMessages();

    console.log('Email Thread (latest):');
    console.log('  Subject:', thread.getFirstMessageSubject());

    // Get the latest message and its attachments
    var latestMessage = messages[messages.length - 1];
    var attachments = latestMessage.getAttachments();

    console.log('  Number of attachments:', attachments.length);

    // Iterate through all attachments
    for (var i = 0; i < attachments.length; i++) {
      var attachment = attachments[i];
      var attachmentName = attachment.getName();

      console.log('    Processing attachment:', attachmentName);

      // Check if the attachment name matches the pattern
      if (attachmentName.match(expectedFileNamePattern)) { 
        // Download the attachment to the source folder
        var sourceFolder = DriveApp.getFolderById(sourceFolderId);
        var csvFile = sourceFolder.createFile(attachment.copyBlob()); 
        console.log('      Downloaded attachment:', csvFile.getName());

        // Process the downloaded CSV file
        processCsvFile(csvFile); 
      } else {
        console.log('    Attachment name does not match the pattern. Skipping.');
      }
    }
  } else {
    console.log('  No emails found matching the search criteria.');
  }
}

// Function to process all files in the source folder
function processFilesInFolder() {
  var sourceFolder = DriveApp.getFolderById(sourceFolderId);
  var files = sourceFolder.getFiles();

  while (files.hasNext()) {
    var file = files.next();
    var fileName = file.getName();

    console.log('    Processing file:', fileName);

    if (fileName.match(expectedFileNamePattern)) {
      processCsvFile(file);
    } else {
      console.log('    Attachment name does not match the pattern. Skipping.');
    }
  }
}

// Function to process a CSV file
function processCsvFile(csvFile) {
  try {
    console.log('Processing CSV file:', csvFile.getName()); // Add a log statement

    var csvContent = csvFile.getBlob().getDataAsString(); // Get CSV content directly
    console.log('CSV content:', csvContent); // Log the CSV content

    // 2. Check for column count mismatch AND add commas to empty description columns
    var csvData = Utilities.parseCsv(csvContent);
    csvData.shift(); // Remove header row
    csvData = csvData.filter(row => row.some(cell => cell !== '')); // Remove empty rows
    for (let i = 0; i < csvData.length; i++) {
      if (csvData[i].length < expectedColumnCount) {
        // Add a comma (empty cell) to the end of the row if the description is missing
        csvData[i].push('');
        console.log('Added empty description column to row ' + (i + 1));
      } else if (csvData[i].length > expectedColumnCount) {
        console.error("Error: Row " + (i + 1) + " has too many columns.");
        // You can handle the error here (e.g., remove the row or log it)
      }
    }

    // *** Process all cells: Remove line breaks, THEN truncate ***
    csvData = csvData.map(row => {
      return row.map((cell, columnIndex) => { 
        if (cell) {
          cell = cell.replace(/[\r\n]+/g, ''); // Remove line breaks FIRST!
          cell = cell.substring(0, 100); // Then truncate to 100 characters
        }
        // Remove commas from the final column (assuming index 7)
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

    // Move csvContent outside the try...catch block
    var csvContent = processedCsvContent; 

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

    BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(csvContent));

    console.log("CSV data updated in BigQuery table successfully!");

    // 6. Delete the amended CSV file from Google Drive (optional)
    deleteCsvFile(fileName, sourceFolderId); 

  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack); 
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

