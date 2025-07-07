// --- GLOBAL VARIABLES (Update these) ---
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // My Drive > Temp
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'RemedyICS'; // Your BigQuery dataset ID
var tableId = 'WorkLog';   // Your BigQuery table ID

// --- FUNCTIONS ---

// Function to process all CSV files in the specified folder
function processAllFilesInFolder() {
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFilesByType(MimeType.CSV);
  var fileCount = 0;

  console.log('Starting to process CSV files in folder:', folder.getName());
  console.log('  - Folder ID:', folderId); // Added logging for folder ID

  // Log the number of files found
  console.log('  - Found', folder.getFilesByType(MimeType.CSV).hasNext(), 'CSV files.'); // Added logging

  // Loop through files
  while (files.hasNext()) {
    var file = files.next();
    fileCount++;
    console.log('Processing file (' + fileCount + '):', file.getName());
    console.log('  - File ID:', file.getId()); // Added logging for file ID
    processFile(file);
  }

  console.log('Finished processing', fileCount, 'CSV files.');
}

// Function to process a single CSV file
function processFile(file) {
  try {
    console.log('  - Reading CSV file:', file.getUrl());

    // 1. Read CSV content as a Blob
    var csvBlob = file.getBlob(); 

    // 2. Remove the header row
    var csvData = Utilities.parseCsv(csvBlob.getDataAsString());
    csvData.shift(); // Remove the first row (header)

    // 3. Convert the filtered data back to CSV string
    var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

    // 4. Save processed CSV to Drive (Optional - for debugging or backup)
    var originalFileName = file.getName();
    var amendedFileName = originalFileName.replace(/\.[^/.]+$/, '') + '_amended.csv';
    var folder = DriveApp.getFolderById(folderId);
    folder.createFile(amendedFileName, processedCsvContent);
    console.log('  - Processed file saved as:', amendedFileName);

    // 5. Upload to BigQuery using WRITE_APPEND
    var job = {
      configuration: {
        load: {
          destinationTable: {
            projectId: projectId,
            datasetId: datasetId,
            tableId: tableId,
          },
          sourceFormat: 'CSV',
          skipLeadingRows: 0, // Now that the header is removed, skip 0 rows
          writeDisposition: 'WRITE_APPEND', // Append to the table
          allowQuotedNewlines: true, 
        },
      },
    };
    
    // Create a new Blob from the processed content
    var processedCsvBlob = Utilities.newBlob(processedCsvContent, 'application/octet-stream');
    BigQuery.Jobs.insert(job, projectId, processedCsvBlob);

    console.log('  - Data from', file.getName(), 'appended to BigQuery successfully!');

  } catch (error) {
    console.error('  - Error processing file:', file.getName(), error);
  }
}

// --- RUN THE PROCESSING MANUALLY ---
function runManualProcessing() {
  processAllFilesInFolder();
}