// drop bmc worklog extract into temp folder and run, will truncate into staging worklog table and merge into target worklog table
var folderId = '1-CN9TVdXLQlG033djKVG5slzbhADbpdA'; // Source folder ID
var archiveFolderId = '1FKlBfbLfnlOqciQYIfR9ORcfK7crpAtT'; // Archive folder ID
var projectId = 'pccw-internal-virt-agent-uat';
var datasetId = 'Staging';
var tableId = 'WorkLog2';
var targetDatasetId = 'Testing';
var targetTableId = 'WorkLog2';


// --- FUNCTIONS ---

function processFilesInFolder() {
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFiles();
  while (files.hasNext()) {
    var file = files.next();
    processFile(file);
  }
}

function processFile(file) {
  try {
    var fileName = file.getName(); // Get filename
    if (file.getMimeType() === MimeType.CSV) {
      var csvData = Utilities.parseCsv(file.getBlob().getDataAsString());

      if (csvData.length > 0 && csvData[0].length > 1) {
        csvData.shift(); // Remove header row
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
              writeDisposition: 'WRITE_TRUNCATE', // Changed to APPEND
              allowQuotedNewlines: true,
            },
          },
        };

        var processedCsvBlob = Utilities.newBlob(processedCsvContent, 'application/octet-stream');
        BigQuery.Jobs.insert(job, projectId, processedCsvBlob);

        moveToArchive(file);

        mergeToTargetTable();

        Logger.log('File processed successfully: ' + fileName); 

      } else {
        Logger.log('Warning: Invalid CSV file: ' + fileName);
      }
    } else {
      Logger.log('Warning: Non-CSV file skipped: ' + fileName);
    }
  } catch (error) {
    Logger.log('Error processing file: ' + fileName + ', Error: ' + error); 
  }
}

function moveToArchive(file) {
  var archiveFolder = DriveApp.getFolderById(archiveFolderId);
  file.moveTo(archiveFolder);
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