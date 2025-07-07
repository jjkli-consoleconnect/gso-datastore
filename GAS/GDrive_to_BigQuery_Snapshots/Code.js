// Source, target, and archive folder IDs 
var sourceFolderId = '1iSF5qkAXlpGGNiBvJaR3i3TpOF8EKK34'; 
var targetFolderId = '1D_IEgkNsPqM8I-aYaC8rhtTcqC7jsco1';
var archiveFolderId = '1jlW4FjADMLhY8PuoJR4Y8ZVP5YCZpXYf';

// Function to process a Google Sheet and append to BigQuery
function processSheetAndAppendToBigQuery(file) {
  try {
    var fileName = file.getName();
    var fileMimeType = file.getMimeType();

    if (fileMimeType === MimeType.GOOGLE_SHEETS) {
      console.log('Processing Google Sheet: ' + fileName);

      // 1. Open the spreadsheet and get data
      var spreadsheet = SpreadsheetApp.openById(file.getId());
      var sheet = spreadsheet.getSheets()[0];
      var data = sheet.getDataRange().getValues();
      data.shift(); // Remove the header row

      // 2. Convert data to CSV format
      var csvContent = data.map(function(row) {
        return row.join(',');
      }).join('\n');

      // 3. Append CSV data to BigQuery
      var projectId = 'pccw-internal-virt-agent-uat';
      var datasetId = 'outstanding_snapshots';
      var tableId = 'snapshots';

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
            writeDisposition: 'WRITE_APPEND'
          }
        }
      };

      BigQuery.Jobs.insert(job, projectId, Utilities.newBlob(csvContent));
      console.log('Data appended to BigQuery successfully!');

      // 4. Move processed Google Sheet to the archive folder
      var archiveFolder = DriveApp.getFolderById(archiveFolderId);
      file.moveTo(archiveFolder);
      console.log('Google Sheet moved to archive folder:', fileName);

    } else {
      console.error('The provided file is not a Google Sheet.');
    }
  } catch (error) {
    console.error('Error processing file:', error);
  }
}

// Function triggered every minute by the time-driven trigger
function checkForNewFiles() {
  try {
    var sourceFolder = DriveApp.getFolderById(sourceFolderId);
    var files = sourceFolder.getFiles();

    while (files.hasNext()) {
      var file = files.next();
      processSheetAndAppendToBigQuery(file);
    }
  } catch (error) {
    console.error('Error checking for new files:', error);
  }
}

// Trigger setup function (run this ONCE)
function createTrigger() {
  // Delete any existing "checkForNewFiles" triggers
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'checkForNewFiles') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  // Create new triggers for 07:15, 15:15, and 23:15 daily
  createDailyTrigger('checkForNewFiles', 7, 15);
  createDailyTrigger('checkForNewFiles', 15, 15);
  createDailyTrigger('checkForNewFiles', 23, 15);

  console.log('Triggers created successfully!');
}

// Helper function to create a daily trigger at a specific hour and minute
function createDailyTrigger(functionName, hour, minute) {
  ScriptApp.newTrigger(functionName)
    .timeBased()
    .atHour(hour)
    .nearMinute(minute)
    .everyDays(1)
    .create();
}