function processDirectCostFiles() {
  const folderId = '1Zzv2go1SaLZ0rdLOX1-ygi6h9ZOth7L2';
  const projectId = 'pccw-internal-virt-agent-uat';
  const datasetId = 'CostItemExpiration';
  const targetTableId = 'DirectCostAllWeeklySnapshot';
  const tempTablePrefix = 'temp_directcost_';
  const uuid = Utilities.getUuid().replace(/-/g, '');
  const tempTableId = tempTablePrefix + uuid;

  const folder = DriveApp.getFolderById(folderId);
  const files = folder.getFilesByType(MimeType.CSV);

  let latestFile = null;
  let latestDate = new Date(0);

  // Find the latest file based on filename date
  while (files.hasNext()) {
    const file = files.next();
    const fileName = file.getName();
    const dateMatch = fileName.match(/weekly_all_direct_cost_report_(\d{4}-\d{2}-\d{2})T/);
    if (dateMatch) {
      const fileDate = new Date(dateMatch[1] + 'T00:00:00');
      if (fileDate > latestDate) {
        latestDate = fileDate;
        latestFile = file;
      }
    }
  }

  if (!latestFile) {
    Logger.log('No valid files found.');
    return;
  }

  Logger.log('Processing latest file: ' + latestFile.getName());

  let allFilteredRows = [];

  const fileName = latestFile.getName();
  const dateMatch = fileName.match(/weekly_all_direct_cost_report_(\d{4}-\d{2}-\d{2})T/);
  const fileDateStr = dateMatch[1];
  const fileDate = new Date(fileDateStr + 'T00:00:00');
  const cutoffDate = new Date(fileDate.getFullYear(), fileDate.getMonth() + 3, fileDate.getDate());

  try {
    const csvBlob = latestFile.getBlob();
    const csvContent = csvBlob.getDataAsString('UTF-8');
    const csvData = Utilities.parseCsv(csvContent);
    const headers = csvData[0];
    const rows = csvData.slice(1);

    rows.forEach(row => {
      const rowObj = {};
      headers.forEach((header, index) => {
        rowObj[header] = row[index] || '';
      });

      // Filter 1: MRC_USD != 0
      const mrcUsd = parseFloat(rowObj['MRC_USD']);
      if (isNaN(mrcUsd) || mrcUsd === 0) return;

      // Filter 2: StopBillingDate within cutoff or null
      const stopDateStr = rowObj['StopBillingDate'];
      if (stopDateStr) {
        let stopDate = null;
        if (/^\d+(\.\d+)?$/.test(stopDateStr)) {
          stopDate = new Date((parseFloat(stopDateStr) - 25569) * 86400 * 1000);
        } else {
          const parsedDate = new Date(stopDateStr);
          if (!isNaN(parsedDate)) {
            stopDate = parsedDate;
          }
        }
        if (stopDate && stopDate > cutoffDate) return;
      }

      allFilteredRows.push(rowObj);
    });
  } catch (e) {
    Logger.log('Error processing file ' + fileName + ': ' + e);
    return;
  }

  if (allFilteredRows.length === 0) {
    Logger.log('No data to process.');
    return;
  }

  // Define schema (all as STRING for simplicity)
  const schema = allFilteredRows[0] ? Object.keys(allFilteredRows[0]).map(field => ({ name: field, type: 'STRING' })) : [];

  // Create temp table
  BigQuery.Tables.insert({
    tableReference: { projectId, datasetId, tableId: tempTableId },
    schema: { fields: schema }
  }, projectId, datasetId);

  // Insert data into temp table
  const insertRequest = {
    rows: allFilteredRows.map(row => ({
      json: row
    }))
  };
  BigQuery.Tabledata.insertAll(insertRequest, projectId, datasetId, tempTableId);

  // Check if target table exists, create if not
  try {
    BigQuery.Tables.get(projectId, datasetId, targetTableId);
  } catch (e) {
    BigQuery.Tables.insert({
      tableReference: { projectId, datasetId, tableId: targetTableId },
      schema: { fields: schema }
    }, projectId, datasetId);
  }

  // Merge query
  const mergeQuery = `
    MERGE \`${projectId}.${datasetId}.${targetTableId}\` t
    USING \`${projectId}.${datasetId}.${tempTableId}\` s
    ON t.CostItemID = s.CostItemID AND t.snapshot_date = s.snapshot_date
    WHEN MATCHED THEN
      UPDATE SET ${Object.keys(allFilteredRows[0]).map(field => `t.${field} = s.${field}`).join(', ')}
    WHEN NOT MATCHED THEN
      INSERT (${Object.keys(allFilteredRows[0]).join(', ')})
      VALUES (${Object.keys(allFilteredRows[0]).map(field => `s.${field}`).join(', ')})
  `;

  const queryRequest = {
    query: mergeQuery,
    useLegacySql: false
  };
  BigQuery.Jobs.query(queryRequest, projectId);

  // Delete temp table
  BigQuery.Tables.remove(projectId, datasetId, tempTableId);

  Logger.log('Process completed. Processed ' + allFilteredRows.length + ' rows.');
}

function myFunction() {
  processDirectCostFiles();
}

