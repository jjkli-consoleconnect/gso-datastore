function insertDataToBigQuery() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Sheet1');

  if (!sheet) {
    Logger.log('Error: Sheet "Sheet1" not found.');
    return;
  }

  const dataRange = sheet.getDataRange();
  const values = dataRange.getValues();
  values.shift(); // Remove header row

  const uniqueRowsMap = new Map(); 
  let duplicateCount = 0; 
  let nonStringCount = 0; 

  values.forEach(row => {
    // Convert timestamp to the correct format
    let timestamp = row[4];
    try {
      timestamp = new Date(timestamp).toISOString().replace('T', ' ').replace('Z', '');
    } catch {
      timestamp = null;
    }
    row[4] = timestamp;

    if (typeof row[2] !== 'string') {
      Logger.log('Non-string Subject value: ' + row[2] + ', Type: ' + typeof row[2]);
      nonStringCount++;
    }

    row[2] = (row[2] && typeof row[2] === 'string') ? row[2].replace(/"/g, '""') : '';
    row[3] = (row[3] && typeof row[3] === 'string') ? row[3].replace(/"/g, '""') : '';

    // Create a composite key using all five columns
    const rowKey = `${row[0]}|${row[1]}|${row[2]}|${row[3]}|${row[4]}`;

    if (!uniqueRowsMap.has(rowKey)) {
      uniqueRowsMap.set(rowKey, row);
    } else {
      duplicateCount++;
    }
  });

  Logger.log(`Total duplicates removed: ${duplicateCount}`);
  Logger.log(`Total non-string Subject values found: ${nonStringCount}`);

  const uniqueRows = Array.from(uniqueRowsMap.values());

  const projectId = 'pccw-internal-virt-agent-uat';
  const stagingDatasetId = 'Staging';
  const stagingTableId = 'GSOCPHStaging';
  const targetDatasetId = 'RemedyICS';
  const targetTableId = 'GSOCPHMailbox';
  const bigquery = BigQuery;

  try {
    // Truncate staging table
    const deleteJob = {
      configuration: {
        query: {
          query: `TRUNCATE TABLE \`${projectId}.${stagingDatasetId}.${stagingTableId}\``,
          useLegacySql: false,
        },
      },
    };
    bigquery.Jobs.insert(deleteJob, projectId);

    // Prepare CSV data
    const csvData = uniqueRows.map(row => `"${row.join('","')}"`).join('\n');
    const csvBlob = Utilities.newBlob(csvData, 'application/octet-stream');

    // Load data into BigQuery
    const insertJob = {
      configuration: {
        load: {
          destinationTable: {
            projectId: projectId,
            datasetId: stagingDatasetId,
            tableId: stagingTableId,
          },
          sourceFormat: 'CSV',
          writeDisposition: 'WRITE_TRUNCATE',
          skipLeadingRows: 1,
          schema: {
            fields: [
              { name: 'MessageID', type: 'STRING', mode: 'NULLABLE' },
              { name: 'ThreadID', type: 'STRING', mode: 'NULLABLE' },
              { name: 'Subject', type: 'STRING', mode: 'NULLABLE' },
              { name: 'From', type: 'STRING', mode: 'NULLABLE' },
              { name: 'ReceivedTimestamp', type: 'TIMESTAMP', mode: 'NULLABLE' },
            ],
          },
        },
      },
    };
    const insertResponse = bigquery.Jobs.insert(insertJob, projectId, csvBlob);
    const jobId = insertResponse.jobReference.jobId;

    let jobStatus;
    do {
      jobStatus = bigquery.Jobs.get(projectId, jobId);
      Logger.log('Job status: ' + jobStatus.status.state);
      Utilities.sleep(5000);
    } while (jobStatus.status.state !== 'DONE');

    // Merge data into the final table
    const mergeQuery = `
      MERGE \`${projectId}.${targetDatasetId}.${targetTableId}\` T
      USING \`${projectId}.${stagingDatasetId}.${stagingTableId}\` S
      ON T.messageId = S.MessageID AND 
         T.threadId = S.ThreadID AND 
         T.subject = S.Subject AND 
         T.sender = S.From AND 
         T.receivedTimestamp = S.ReceivedTimestamp
      WHEN MATCHED THEN
        UPDATE SET T.subject = S.Subject, T.sender = S.From, T.threadId = S.ThreadID, T.receivedTimestamp = S.ReceivedTimestamp
      WHEN NOT MATCHED THEN
        INSERT (messageId, threadId, subject, sender, receivedTimestamp)
        VALUES (S.MessageID, S.ThreadID, S.Subject, S.From, S.ReceivedTimestamp)
    `;

    const mergeJob = {
      configuration: {
        query: {
          query: mergeQuery,
          useLegacySql: false,
        },
      },
    };

    const mergeResponse = bigquery.Jobs.insert(mergeJob, projectId);
    Logger.log('Merge Job Response: ' + JSON.stringify(mergeResponse));

    Logger.log('Merge operation completed successfully');

    // Clear all rows below the header row in Google Sheets
    const lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).clearContent();
      Logger.log('Data cleared from Google Sheet, header row left intact');
    }

  } catch (error) {
    Logger.log('Error: ' + error);
  }
}