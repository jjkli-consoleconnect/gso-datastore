function processUserListReport() {
  const sourceLabel = GmailApp.getUserLabelByName("CloudWatch");
  const archiveLabel = GmailApp.getUserLabelByName("ArchivedReports");
  const threads = sourceLabel.getThreads();
  let targetMessage = null;
  let sourceThread = null;

  // Step 1: Find unread email with matching subject
  for (let thread of threads) {
    if (thread.isUnread()) {
      const messages = thread.getMessages();
      for (let message of messages) {
        if (message.getSubject().trim() === "BQ - BMC User List") {
          targetMessage = message;
          sourceThread = thread;
          break;
        }
      }
    }
    if (targetMessage) break;
  }

  if (!targetMessage) {
    Logger.log("No unread email found with subject 'BQ - BMC User List'.");
    return;
  }

  // Step 2: Extract CSV attachment and parse
  const attachments = targetMessage.getAttachments();
  const csvFile = attachments.find(att => att.getName().endsWith(".csv"));

  if (!csvFile) {
    Logger.log("No CSV attachment found.");
    return;
  }

  const csvData = Utilities.parseCsv(csvFile.getDataAsString());
  const headers = csvData[0];
  const records = csvData.slice(1).map(row => {
    const obj = {};
    headers.forEach((h, i) => {
      obj[h] = row[i];
    });
    return obj;
  });

  Logger.log(`Parsed ${records.length} records from CSV.`);

  // Step 3: Insert into BigQuery (overwrite logic)
  const targetTables = [
    'pccw-internal-virtual-agent.BMC.UserList',
    'pccw-internal-virt-agent-uat.BMC.UserList'
  ];

  targetTables.forEach(fullTableId => {
    const [projectId, datasetId, tableId] = fullTableId.split('.');
    
    const table = BigQuery.Tables.get(projectId, datasetId, tableId);
    
    if (table) {
      // Clear the table before insert (by deleting then recreating schema, OR overwrite via job)
      const insertResponse = BigQuery.Jobs.insert({
        configuration: {
          load: {
            destinationTable: {
              projectId,
              datasetId,
              tableId
            },
            writeDisposition: "WRITE_TRUNCATE",
            sourceFormat: "NEWLINE_DELIMITED_JSON",
            schema: {
              fields: headers.map(h => ({ name: h, type: "STRING" }))
            }
          }
        }
      }, projectId, Utilities.newBlob(records.map(r => JSON.stringify(r)).join("\n"), "application/json"));

      Logger.log(`Insert job for ${fullTableId} submitted: ${insertResponse.jobReference.jobId}`);
    } else {
      Logger.log(`Table ${fullTableId} not found.`);
    }
  });

  // Step 4: Label cleanup
  if (archiveLabel) {
    sourceThread.removeLabel(sourceLabel);
    sourceThread.addLabel(archiveLabel);
    Logger.log("Email labels updated: Removed 'CloudWatch', added 'ArchivedReports'.");
  } else {
    Logger.log("ArchivedReports label not found. Skipping label update.");
  }

  sourceThread.markRead();
}

// Run this once to schedule the weekly trigger
function createWeeklyTrigger() {
  ScriptApp.newTrigger("processUserListReport")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SUNDAY)
    .atHour(10)
    .create();
}

function debugSubjects() {
  const label = GmailApp.getUserLabelByName("CloudWatch");
  const threads = label.getThreads();
  threads.forEach(thread => {
    thread.getMessages().forEach(msg => {
      Logger.log(`Subject: "${msg.getSubject()}"`);
    });
  });
}

