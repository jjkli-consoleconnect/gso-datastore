// --- GLOBAL VARIABLES ---
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; 
var subject = 'Automated Datapipe - WorkLog'; 
var sender = 'noreply-bmchelix@onbmc.com'; 
var label = 'Dashboard/AutoReports'; 
var projectId = 'pccw-internal-virt-agent-uat'; 
var datasetId = 'Staging'; 
var tableId = 'WorkLog';   
var archivedLabel = 'ArchivedReports'; 

// --- Target Table Information ---
var targetDatasetId = 'RemedyICS'; 
var targetTableId = 'WorkLog'; 

// --- FUNCTIONS ---

function searchForEmailAndAttachments() {
  var searchQuery = 'subject:' + subject + ' from:' + sender + ' label:' + label;
  var threads = GmailApp.search(searchQuery);
  Logger.log("Emails found: " + threads.length);

  //Sort emails by date (newest first) - optional if order doesn't matter
  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  //Iterate through ALL threads
  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var messages = thread.getMessages();
    var latestMessage = messages[messages.length - 1]; // Get the latest message in the thread
    var attachments = latestMessage.getAttachments();
    Logger.log('Processing email ' + (i+1) + ' of ' + threads.length + ': Attachments found: ' + attachments.length);

    if (attachments.length > 0) {
      attachments.forEach(processAttachment);
      //Move email to archive AFTER processing attachments
      var archivedLabelObj = GmailApp.getUserLabelByName(archivedLabel);
      var dashboardLabelObj = GmailApp.getUserLabelByName(label);
      thread.removeLabel(dashboardLabelObj);
      thread.addLabel(archivedLabelObj);
    } else {
      Logger.log('Email ' + (i+1) + ' of ' + threads.length + ' has no attachments.');
    }
  }
}

function processAttachment(attachment) {
  try {
    var blob = attachment.copyBlob(); 
    var folder = DriveApp.getFolderById(folderId);
    var file = folder.createFile(blob.setName(attachment.getName())); 

    if (file && file.getName()) {
      if (file.getMimeType() === MimeType.CSV) {
        var csvBlob = file.getBlob();
        var csvData = Utilities.parseCsv(csvBlob.getDataAsString());

        if (csvData.length > 0 && csvData[0].length > 1) { 
          csvData.shift(); 
          var processedCsvContent = csvData.map(row => row.join(',')).join('\n');

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
                writeDisposition: 'WRITE_TRUNCATE', 
                allowQuotedNewlines: true, 
              },
            },
          };

          var processedCsvBlob = Utilities.newBlob(processedCsvContent, 'application/octet-stream');
          var loadJob = BigQuery.Jobs.insert(job, projectId, processedCsvBlob);

          var loadJobId = loadJob.jobReference.jobId;
          var loadJobStatus = BigQuery.Jobs.get(projectId, loadJobId);
          while (loadJobStatus.status.state !== 'DONE') {
            Utilities.sleep(2000); 
            loadJobStatus = BigQuery.Jobs.get(projectId, loadJobId);
          }

          if (loadJobStatus.status.errorResult) {
            Logger.log('Error: BigQuery load job failed: ' + loadJobStatus.status.errorResult.message);
            throw new Error('BigQuery load failed'); 
          } else {
            Logger.log('Data successfully loaded to staging table.');
            mergeToTargetTable(); // Call the merge function after the load job is done
          }

          file.setTrashed(true);

        } else {
          Logger.log('Warning: Invalid CSV file: ' + file.getName());
        }

      } else {
        Logger.log('Warning: Non-CSV attachment skipped: ' + file.getName()); 
      }
    }

  } catch (error) {
    Logger.log('Error processing attachment: ' + attachment.getName() + ', Error: ' + error); 
  }
}

function mergeToTargetTable() {
  var query = `
    MERGE \`${projectId}.${targetDatasetId}.${targetTableId}\` T
    USING \`${projectId}.${datasetId}.${tableId}\` S
    ON T.WorkLogID = S.WorkLogID
    WHEN MATCHED THEN
      UPDATE SET 
        T.IncidentNumber = S.IncidentNumber,
        T.WorkLogSubmitDate = S.WorkLogSubmitDate,
        T.WorkLogSubmitter = S.WorkLogSubmitter,
        T.LastModifiedDate = S.LastModifiedDate,
        T.LastModifiedBy = S.LastModifiedBy,
        T.EffortTimeSpent_mins = S.EffortTimeSpent_mins,
        T.WorkLogType = S.WorkLogType,
        T.DetailedDescription = S.DetailedDescription
    WHEN NOT MATCHED THEN
      INSERT (WorkLogID, IncidentNumber, WorkLogSubmitDate, WorkLogSubmitter, LastModifiedDate, LastModifiedBy, EffortTimeSpent_mins, WorkLogType, DetailedDescription)
      VALUES (S.WorkLogID, S.IncidentNumber, S.WorkLogSubmitDate, S.WorkLogSubmitter, S.LastModifiedDate, S.LastModifiedBy, S.EffortTimeSpent_mins, S.WorkLogType, S.DetailedDescription);
  `;

  var job = {
    configuration: {
      query: {
        query: query,
        useLegacySql: false
      }
    }
  };

  var jobResponse = BigQuery.Jobs.insert(job, projectId);
  var jobId = jobResponse.jobReference.jobId;

  var jobStatus = BigQuery.Jobs.get(projectId, jobId);
  while (jobStatus.status.state !== 'DONE') {
    Utilities.sleep(2000); 
    jobStatus = BigQuery.Jobs.get(projectId, jobId);
  }

  if (jobStatus.status.errorResult) {
    Logger.log('Error: BigQuery MERGE job failed: ' + jobStatus.status.errorResult.message);
    throw new Error('BigQuery MERGE failed'); 
  } else {
    Logger.log('Data successfully merged to target table.');
  }
}
