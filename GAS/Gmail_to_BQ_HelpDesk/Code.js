// --- GLOBAL VARIABLES ---
var scriptName = "Automated Datapipe - HelpDesk Script"; // Add your script's name here
var subject = 'Automated Datapipe - HelpDesk';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'Staging';
var tableId = 'HelpDesk';
var targetDatasetId = 'RemedyICS';
var targetTableId = 'HelpDesk';
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA';
var errorNotificationEmails = 'jjkli@consoleconnect.com, aaaakavus5zpprof6yndvck2lm@consoleconnect.com';
var archivedLabel = 'ArchivedReports';

// --- FUNCTIONS ---
function searchForEmailAndAttachments() {
  var searchQuery = 'subject:"' + subject + '" from:' + sender + ' label:"' + label + '"';
  var threads = GmailApp.search(searchQuery);

  console.log("Number of emails found:", threads.length);

  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  if (threads.length > 0) {

    var latestThread = threads[0];
    var emailSubject = latestThread.getFirstMessageSubject().trim(); // TRIM THE EMAIL SUBJECT
    console.log('Latest Email Thread:');
    console.log('  Subject:', emailSubject);

    // ADD THIS CONDITION HERE, THE MOST IMPORTANT PART
    if (emailSubject === subject) {

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
    } else {
      console.log('  Subject Mismatch after trim. Skipping this email.');
    }
  } else {
    console.log("No emails found matching the search criteria.");
  }
}

function processAttachment(attachment) {
  try {
    if (attachment) {
      var csvData = Utilities.parseCsv(attachment.getDataAsString());
      csvData.shift();
      csvData = csvData.filter(row => row.some(cell => cell !== ''));

      const expectedColumnCount = 29; // Updated column count
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

      var loadJob = {
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
      var job = BigQuery.Jobs.insert(loadJob, projectId, Utilities.newBlob(processedCsvContent));
      waitForJobCompletion(job);

      console.log("Staging table updated successfully!");

      mergeTablesInBigQuery();
      deleteCsvFile(fileName, folderId);

    } else {
      console.log("No attachment found in this email.");
    }
  } catch (error) {
    console.error("Error processing attachment:", error);
    console.error(error.stack);
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: 'Error in ' + scriptName, // Include script name in subject
      body: 'An error occurred while processing the attachment: \n\n' + error.message + '\n\n' + error.stack
    });
  }
}

function waitForJobCompletion(job) {
  while (job.status && job.status.state !== "DONE") {
    Utilities.sleep(5000); // Wait 5 seconds
    job = BigQuery.Jobs.get(projectId, job.jobReference.jobId);
  }
  if (job.status.errorResult) {
    throw new Error("BigQuery load job failed: " + job.status.errorResult.message);
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

function mergeTablesInBigQuery() {
  try {
    var query = `
      MERGE \`${projectId}.${targetDatasetId}.${targetTableId}\` T
      USING \`${projectId}.${datasetId}.${tableId}\` H
      ON T.Incident_Number = H.Incident_Number
      WHEN MATCHED THEN
        UPDATE SET
          T.Status = H.Status,
          T.CaseType = H.CaseType,
          T.Assigned_Group = H.Assigned_Group,
          T.Categorization_Tier_1 = H.Categorization_Tier_1,
          T.Categorization_Tier_2 = H.Categorization_Tier_2,
          T.Categorization_Tier_3 = H.Categorization_Tier_3,
          T.GCSC_1st_Customer_Update = H.GCSC_1st_Customer_Update,
          T.GCSC_2nd_Customer_Update = H.GCSC_2nd_Customer_Update,
          T.GCSC_3rd_Customer_Update = H.GCSC_3rd_Customer_Update,
          T.Initial_Response_Time = H.Initial_Response_Time,
          T.Second_Response_Time = H.Second_Response_Time,
          T.Third_Response_Time = H.Third_Response_Time,
          T.Prod_ID = H.Prod_ID,
          T.Fault_Cause = H.Fault_Cause,
          T.Closed_Date = H.Closed_Date,
          T.Submit_Date = H.Submit_Date,
          T.Assignee = H.Assignee,
          T.Closed_By = H.Closed_By,
          T.Submitter = H.Submitter,
          T.TrueMTTR_mins = H.TrueMTTR_mins,
          T.Cust_ID = H.Cust_ID,
          T.Carrier = H.Carrier,
          T.Customer_Name = H.Customer_Name,
          T.SRno = H.SRno,
          T.LastResolvedDate = H.LastResolvedDate,
          T.ReportedDate = H.ReportedDate,
          T.RespondedDate = H.RespondedDate,
          T.FaultCauseDetail = H.FaultCauseDetail
      WHEN NOT MATCHED THEN
        INSERT (
          Incident_Number, Status, CaseType, Assigned_Group, Categorization_Tier_1,
          Categorization_Tier_2, Categorization_Tier_3, GCSC_1st_Customer_Update,
          GCSC_2nd_Customer_Update, GCSC_3rd_Customer_Update, Initial_Response_Time,
          Second_Response_Time, Third_Response_Time, Prod_ID, Fault_Cause, Closed_Date,
          Submit_Date, Assignee, Closed_By, Submitter, TrueMTTR_mins, Cust_ID, Carrier,
          Customer_Name, SRno, LastResolvedDate, ReportedDate, RespondedDate, FaultCauseDetail
        )
        VALUES (
          H.Incident_Number, H.Status, H.CaseType, H.Assigned_Group, H.Categorization_Tier_1,
          H.Categorization_Tier_2, H.Categorization_Tier_3, H.GCSC_1st_Customer_Update,
          H.GCSC_2nd_Customer_Update, H.GCSC_3rd_Customer_Update, Initial_Response_Time,
          H.Second_Response_Time, Third_Response_Time, Prod_ID, Fault_Cause, Closed_Date,
          Submit_Date, Assignee, Closed_By, Submitter, TrueMTTR_mins, Cust_ID, Carrier,
          Customer_Name, SRno, LastResolvedDate, ReportedDate, RespondedDate, FaultCauseDetail
        );
    `;

    var job = {
      configuration: {
        query: {
          query: query,
          useLegacySql: false
        }
      }
    };

    BigQuery.Jobs.insert(job, projectId);
    console.log("Tables merged successfully in BigQuery!");
  } catch (error) {
    console.error("Error merging tables in BigQuery:", error);
    console.error(error.stack);
    MailApp.sendEmail({
      to: errorNotificationEmails,
      subject: 'Error in ' + scriptName, // Include script name in subject
      body: 'An error occurred while merging tables in BigQuery: \n\n' + error.message + '\n\n' + error.stack
    });
  }
}

function main() { //added main function to call
  searchForEmailAndAttachments();
}