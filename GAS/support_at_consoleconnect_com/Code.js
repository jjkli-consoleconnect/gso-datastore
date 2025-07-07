// --- GLOBAL VARIABLES (Update these if needed) ---
var projectId = 'pccw-internal-virt-agent-uat'; // Your BigQuery project ID
var datasetId = 'RemedyICS'; // Your BigQuery dataset ID
var tableId = 'SupportMailbox'; // Your BigQuery table ID
var labelName = 'support@consoleconnect.com'; // Label to search for
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // Google Drive folder ID 

// Function to search for unread emails in the last 7 days
function searchForUnreadEmails() {
  var today = new Date();
  var twoDaysAgo = new Date();
  twoDaysAgo.setDate(today.getDate() - 7);

  // Search query for unread emails within the last two days
  var searchQuery = 'is:unread label:' + labelName + ' after:' + 
                    twoDaysAgo.getFullYear() + '/' + (twoDaysAgo.getMonth() + 1) + '/' + twoDaysAgo.getDate();

  var threads = GmailApp.search(searchQuery);
  return threads;
}

// Function to extract email data
function extractEmailData(thread) {
  var messages = thread.getMessages();
  var latestMessage = messages[messages.length - 1]; 

  var subject = latestMessage.getSubject().replace(/,/g, ' '); // Replace commas with spaces for safety
  var sender = latestMessage.getFrom().replace(/,/g, ';').replace(/"/g, "'"); // Replace commas with semicolons and escape quotes
  var threadId = thread.getId(); 
  var messageId = latestMessage.getId(); 
  var receivedTimestamp = latestMessage.getDate();  

  // Format receivedTimestamp to YYYY-MM-DD HH:mm:ss in UTC
  receivedTimestamp = Utilities.formatDate(new Date(receivedTimestamp), "GMT", "yyyy-MM-dd HH:mm:ss");

  return [sender, subject, threadId, receivedTimestamp, messageId]; 
}

// Function to create a CSV file in Google Drive
function createCSVFile(dataRows) {
  var csvContent = 'sender,subject,threadId,receivedTimestamp,messageId\n'; 
  dataRows.forEach(function(row) {
    csvContent += row.join(',') + '\n';
  });
  var folder = DriveApp.getFolderById(folderId);
  var file = folder.createFile('emails.csv', csvContent);
  return file;
}

// Function to load data to BigQuery and delete the CSV file
function loadToBigQuery(csvFile) {
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
        allowQuotedNewlines: true,
        maxBadRecords: 10 
      }
    }
  };
  try {
    var jobResponse = BigQuery.Jobs.insert(job, projectId, csvFile);
    console.log('Job ID: ' + jobResponse.jobReference.jobId);
    console.log('Job Status: ' + jobResponse.status.state);
    // Delete the CSV file after successful upload
    csvFile.setTrashed(true);
    console.log('CSV file deleted successfully.');
  } catch (error) {
    console.error('Error loading data to BigQuery or deleting CSV:', error);
  }
}

// Function to mark emails as read
function markEmailsAsRead(threads) {
  threads.forEach(function(thread) {
    thread.markRead();
  });
}

// Main function to run the script
function extractEmailsToBigQuery() {
  var threads = searchForUnreadEmails();
  console.log('Number of unread emails found in the last 7 days: ' + threads.length);

  var dataRows = [];
  console.log('Starting to extract data from threads...'); 
  threads.forEach(function(thread) {
    var emailData = extractEmailData(thread);
    dataRows.push(emailData); 
  });
  console.log('Finished extracting data.');

  console.log('Creating CSV file...');
  var csvFile = createCSVFile(dataRows);
  console.log('Finished creating CSV file.');
  console.log('CSV file ID: ' + csvFile.getId());

  console.log('Loading data to BigQuery...');
  loadToBigQuery(csvFile);
  console.log('Finished loading data to BigQuery.');

  console.log('Marking emails as read...');
  markEmailsAsRead(threads);
  console.log('Finished marking emails as read.');
}

// Call the main function
extractEmailsToBigQuery();

//Optional: uncomment to create a daily trigger. Remember to save the script after uncommenting.
/*
function createTrigger() {
  ScriptApp.newTrigger('extractEmailsToBigQuery')
      .timeBased()
      .everyDays(1)
      .atHour(8) // Adjust time as needed
      .create();
}
*/