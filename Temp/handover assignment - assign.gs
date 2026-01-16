// --- GLOBAL VARIABLES ---
var subject = 'Automated Report - Automated Handover Queue';
var sender = 'noreply-bmchelix@onbmc.com';
var label = 'Dashboard/AutoReports';
var parentlabel = 'Dashboard';
var processingFolderId = '1o9Rzqk40EB5A0ENUJR2b2V1FZVtvnvbp'; // Processing folder
var expectedFileNamePattern = /^Handover Queue.*\.csv$/;
var formSpreadsheetId = '1iQ00bWMMNIRlOKJwO9y6TZMnaplleRyv0l4NhFOJtfs'; // ID of the form spreadsheet
var formResponseSheetName = 'Form responses 4'; // Name of the form response tab
var staffListSpreadsheetId = '1fDVgoNnWD3DzBLq4kNCLOrz3r5ggT6DQP12-fnZAkrY'; // ID of GS&O Staff Lists spreadsheet
var assignmentHistorySheetName = 'AssignmentHistory';
var archiveFolderId = '1c6HfD5GpZ7WMHgq3CL6cuWmISf82Vdwp'; // Replace with your archive folder ID
var groupEmail = 'jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com';  
//var groupEmail = 'cc-agents-aaaabhow4onydtdkewcpq3b4oq@consoleconnect.org.slack.com, jens-vertexai-aaaan3dj2p4fdro72c3fa2l3km@consoleconnect.org.slack.com';
var archivedLabel = 'ArchivedReports'; // New label name

// --- FUNCTIONS ---

// Main Function
function processEmailsAndAttachments() {
  console.log('   Searching for emails with these criteria:');
  console.log('   Subject:', subject);
  console.log('   Sender:', sender);
  console.log('   Label:', label);

  // Search Gmail with both labels and the subject
  var threads = GmailApp.search('subject:' + subject + ' from:' + sender + ' label:' + label + ' label:' + parentlabel);
  console.log("Number of threads found:", threads.length);

  // Sort threads by last modified date (descending order)
  threads.sort(function(a, b) {
    return b.getLastMessageDate().getTime() - a.getLastMessageDate().getTime();
  });

  // Process the latest thread (if any)
  if (threads.length > 0) {
    var latestThread = threads[0]; // Get the latest thread
    var messages = latestThread.getMessages();

    console.log('Email Thread (latest):');
    console.log(' Subject:', latestThread.getFirstMessageSubject());

    // Get the latest message and its attachments
    var latestMessage = messages[messages.length - 1];
    var attachments = latestMessage.getAttachments();

    console.log(' Number of attachments:', attachments.length);

    // Get the latest attachment that matches the pattern
    var matchingAttachment = getMatchingAttachment(attachments);

    // Process the CSV file (if found)
    if (matchingAttachment) {
      // Download the attachment to Drive
      var downloadedFile = downloadAttachmentToDrive(matchingAttachment);
      console.log('   Downloaded attachment:', downloadedFile.getName());

      // Parse and Convert the CSV to a spreadsheet
      var spreadsheet = createAndPopulateSpreadsheetOptimized(downloadedFile); // Get the created spreadsheet
      if (!spreadsheet) {
        console.error("Spreadsheet creation failed. Exiting thread processing.");
        return; // Exit if spreadsheet creation failed.
      }
      console.log('   Google Sheet created:', DriveApp.getFileById(spreadsheet.getId()).getUrl());

      // Delete the downloaded CSV file
      downloadedFile.setTrashed(true);
      console.log('   CSV file deleted:', downloadedFile.getName());

      // Assign Engineers
      assignEngineersToSpreadsheetOptimized(spreadsheet); // Pass the spreadsheet object
      console.log('Engineers assigned to spreadsheet.');

      // Generate and send Remedy Keys spreadsheet
      generateAndSendAssignments(spreadsheet);
      console.log('Remedy Key Assignments generated and sent.');

      // Move the spreadsheet to the archive folder after everything is done
      moveSpreadsheetToArchive(spreadsheet);
      console.log('Spreadsheet moved to archive.');

      // Remove the 'Dashboard/AutoReports' label
      var autoReportsLabelObj = GmailApp.getUserLabelByName(label);
      if (autoReportsLabelObj) {
        latestThread.removeLabel(autoReportsLabelObj);
        console.log('Removed "' + label + '" label from the email thread.');
      } else {
        console.log('"' + label + '" label not found.');
      }

    } else {
      console.log(' No attachments matching the pattern found.');
    }
  } else {
    console.log(' No emails found matching the search criteria.');
  }
}

// --- Helper Functions ---

function getMatchingAttachment(attachments) {
  // Get the latest attachment that matches the pattern
  var latestMatchingAttachment = null;
  if (attachments.length > 0) {
    for (var i = 0; i < attachments.length; i++) {
      var attachment = attachments[i];
      var attachmentName = attachment.getName();

      console.log('   Attachment Name:', attachmentName);

      // Check if the attachment name matches the regular expression pattern
      if (attachmentName.match(expectedFileNamePattern)) {
        latestMatchingAttachment = attachment;
        break; // Stop the loop once you find the latest matching attachment
      }
    }
  }
  return latestMatchingAttachment;
}

function downloadAttachmentToDrive(attachment) {
  // Download the attachment to Drive
  return DriveApp.getFolderById(processingFolderId).createFile(attachment.copyBlob());
}

function createAndPopulateSpreadsheetOptimized(downloadedFile) {
  var now = new Date();
  var formattedDateTime = now.toISOString().slice(0, 19).replace('T', '_');
  var spreadsheet = SpreadsheetApp.create(formattedDateTime + ' Handover Assignment');
  var sheet = spreadsheet.getSheets()[0];
  sheet.setName('Assignments');

  try {
    // Get CSV data as a string
    var csvData = downloadedFile.getBlob().getDataAsString();

    // Parse CSV data using Utilities.parseCsv
    var data = Utilities.parseCsv(csvData);

    // Check if data is empty or has no rows
    if (!data || data.length === 0) {
      console.error("CSV data is empty or could not be parsed.");
      spreadsheet.setTrashed(true); // Delete the created spreadsheet
      return null; // Return null to indicate failure
    }

    // Get the number of columns in the first row to determine the maximum number of columns
    var numColumns = data[0].length;

    // Write the data in bulk
    var range = sheet.getRange(1, 1, data.length, numColumns);
    range.setValues(data);

    return spreadsheet;

  } catch (e) {
    console.error("Error during CSV parsing or writing:", e);
    spreadsheet.setTrashed(true); // Delete the created spreadsheet
    return null; // Return null to indicate failure
  }
}

function assignEngineersToSpreadsheetOptimized(spreadsheet) {
  // Open the spreadsheet
  var sheet = spreadsheet.getSheetByName('Assignments');

  // Get engineer names from the form spreadsheet (BULK READ)
  var formSpreadsheet = SpreadsheetApp.openById(formSpreadsheetId);
  var formSheet = formSpreadsheet.getSheetByName(formResponseSheetName);
  if (!formSheet) {
    throw new Error('Form response sheet "' + formResponseSheetName + '" not found. Check the sheet name.');
  }
  var lastRow = formSheet.getLastRow();
  if (lastRow < 2) {
    throw new Error('No form responses found in "' + formResponseSheetName + '".');
  }
  var engineerNamesRange = formSheet.getRange(lastRow, 2);
  var engineerNames = engineerNamesRange.getValue(); // Single cell read
  var checkedEngineers = engineerNames.split(',').map(name => name.trim());
  console.log('Engineers from form:', checkedEngineers);

  // Get the last row of the handover spreadsheet
  var lastRowHandover = sheet.getLastRow();

  // Find the first available empty column (Less efficient - could be improved if needed)
  var availableColumn = sheet.getLastColumn() + 1;
  var header = sheet.getRange(1, availableColumn).getValue();

  // Keep searching for an empty column until you find one
  while (header !== "") {
    availableColumn++;
    header = sheet.getRange(1, availableColumn).getValue();
  }

  // Insert the new column for "Assigned Engineer"
  sheet.insertColumnBefore(availableColumn);

  // Set the header for the new column
  sheet.getRange(1, availableColumn).setValue('Assigned Engineer');

  // *** BULK WRITE SECTION ***
  // Read all data, Incident IDs from the sheet
  var dataRange = sheet.getDataRange();
  var data = dataRange.getValues(); // Read all data in one go

  // Dynamically locate the Incident Number column to tolerate layout changes
  var incidentHeader = 'Incident Number';
  var incidentIndex = findHeaderIndex_(data[0], incidentHeader);
  if (incidentIndex === -1) {
    throw new Error('Header "' + incidentHeader + '" not found in the CSV.');
  }

  // Load prior assignments for stickiness
  var historySheet = getOrCreateHistorySheet_(formSpreadsheet, assignmentHistorySheetName);
  var historyMap = loadAssignmentHistory_(historySheet, checkedEngineers);

  // Prepare arrays for assignments and tracking
  var engineerAssignments = new Array(data.length - 1); // index i-1 aligns to row i
  var incidentData = {};
  var engineerLoad = {};
  for (var e = 0; e < checkedEngineers.length; e++) {
    engineerLoad[checkedEngineers[e]] = 0;
  }

  var unassigned = [];
  var now = new Date();
  var historyRowsToAppend = [];

  // First pass: stickies and collect unassigned
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var incidentId = row[incidentIndex];

    var assignedEngineer = historyMap[incidentId] || null;
    if (assignedEngineer) {
      engineerAssignments[i - 1] = assignedEngineer;
      engineerLoad[assignedEngineer] = (engineerLoad[assignedEngineer] || 0) + 1;

      if (!incidentData.hasOwnProperty(assignedEngineer)) {
        incidentData[assignedEngineer] = [];
      }
      incidentData[assignedEngineer].push(incidentId);

      historyRowsToAppend.push([incidentId, assignedEngineer, now, spreadsheet.getId(), spreadsheet.getUrl()]);
    } else {
      unassigned.push({ idx: i - 1, incidentId: incidentId });
    }
  }

  // Helper to find engineer with lowest current load (fair after stickies)
  function pickLeastLoadedEngineer() {
    var minEngineer = checkedEngineers[0];
    var minLoad = engineerLoad[minEngineer] || 0;
    for (var k = 1; k < checkedEngineers.length; k++) {
      var eng = checkedEngineers[k];
      var load = engineerLoad[eng] || 0;
      if (load < minLoad) {
        minLoad = load;
        minEngineer = eng;
      }
    }
    return minEngineer;
  }

  // Second pass: assign remaining using load-aware round robin
  for (var u = 0; u < unassigned.length; u++) {
    var slot = unassigned[u];
    var engChoice = pickLeastLoadedEngineer();
    engineerAssignments[slot.idx] = engChoice;
    engineerLoad[engChoice] = (engineerLoad[engChoice] || 0) + 1;

    if (!incidentData.hasOwnProperty(engChoice)) {
      incidentData[engChoice] = [];
    }
    incidentData[engChoice].push(slot.incidentId);

    historyRowsToAppend.push([slot.incidentId, engChoice, now, spreadsheet.getId(), spreadsheet.getUrl()]);
  }

  // Write engineer assignments in BULK
  var assignmentRows = engineerAssignments.map(function(name) { return [name]; });
  var assignmentRange = sheet.getRange(2, availableColumn, assignmentRows.length, 1);
  assignmentRange.setValues(assignmentRows);

  // Persist assignments for future sticky use
  appendAssignmentHistory_(historySheet, historyRowsToAppend);

  // Create separate tabs for each engineer
  createEngineerTabs(spreadsheet, incidentData);

  // Auto-fit columns A to C on the 'Assignments' sheet
  sheet.autoResizeColumns(1, 3);

  // Move the Assignments sheet to the last tab
  spreadsheet.moveActiveSheet(spreadsheet.getNumSheets());
}

function createEngineerTabs(spreadsheet, incidentData) {
  // Now we do not need to get the Handover Data tab, we work directly with the 'Assignments' sheet
  var assignmentsSheet = spreadsheet.getSheetByName('Assignments');

  // Create tabs for each engineer
  for (var engineer in incidentData) {
    if (incidentData.hasOwnProperty(engineer)) {
      // Create a new sheet for the engineer
      var engineerSheet = spreadsheet.insertSheet(engineer);

      // Set headers
      engineerSheet.getRange(1, 1).setValue('Assigned Engineer');
      engineerSheet.getRange(1, 2).setValue('Incident ID');
      engineerSheet.getRange(1, 3).setValue('Remedy Key'); // Add the Remedy Key header

      // Write the data to the engineer sheet
      var currentRow = 2;
      var values = []; // Array to hold all the row values

      for (var i = 0; i < incidentData[engineer].length; i++) {
        var incidentId = incidentData[engineer][i];
        var remedyKeyFormula;
        var isNewSegment = false;

        // Add blank separator row before each new query segment
        if (currentRow === 90 || currentRow === 180 || currentRow === 270) {
          values.push(['', '', '']); // Add blank row
          currentRow++;
          isNewSegment = true; // Next row starts a new segment
        }

        if (currentRow === 2 || isNewSegment) {
          remedyKeyFormula = "''Incident Number' = \"" + incidentId + "\"";
        } else {
          remedyKeyFormula = "OR 'Incident Number' = \"" + incidentId + "\"";
        }

        values.push([engineer, incidentId, remedyKeyFormula]); // Add a new row
        currentRow++;
      }

      // Write the values in bulk to the engineer sheet
      engineerSheet.getRange(2, 1, values.length, 3).setValues(values);

      engineerSheet.autoResizeColumns(1, 3);
    }
  }
}

function generateAndSendAssignments(spreadsheet) {
  // Don't delete the 'Assignments' sheet
  var assignmentsSheet = spreadsheet.getSheetByName('Assignments'); // Get the Assignments sheet
  var incidentCol = findColumnIndexByHeader_(assignmentsSheet, 'Incident Number');
  var assignedCol = findColumnIndexByHeader_(assignmentsSheet, 'Assigned Engineer');
  var rowCount = assignmentsSheet.getLastRow() - 1;

  // 1. Get data from the spreadsheet using detected columns
  var engineerNames = assignmentsSheet.getRange(2, assignedCol, rowCount, 1).getValues();
  var incidentIds = assignmentsSheet.getRange(2, incidentCol, rowCount, 1).getValues();

  // 2. Group incident IDs by engineer
  var incidentIdsByEngineer = {};
  for (var i = 0; i < engineerNames.length; i++) {
    var engineer = engineerNames[i][0];
    if (!incidentIdsByEngineer.hasOwnProperty(engineer)) {
      incidentIdsByEngineer[engineer] = [];
    }
    incidentIdsByEngineer[engineer].push(incidentIds[i][0]);
  }

  // Send email to each engineer with the spreadsheet as an attachment
  for (var engineer in incidentIdsByEngineer) {
    if (incidentIdsByEngineer.hasOwnProperty(engineer)) {
      sendEmailsToEngineers(spreadsheet, engineer);
    }
  }

  // Send a single email to the group after all individual emails are sent.
  sendGroupEmail(spreadsheet);

  return true; // Return true to indicate success
}

// Function to move the spreadsheet to the archive folder
function moveSpreadsheetToArchive(spreadsheet) {
  var archiveFolder = DriveApp.getFolderById(archiveFolderId);
  var file = DriveApp.getFileById(spreadsheet.getId());
  file.moveTo(archiveFolder);
  console.log('Spreadsheet moved to archive folder:', file.getName());
}

// Function to move the CSV file to the archive folder
function moveFileToArchive(file) {
  var archiveFolder = DriveApp.getFolderById(archiveFolderId);
  file.moveTo(archiveFolder);
  console.log('File moved to archive folder:', file.getName());
}

function sendEmailsToEngineers(spreadsheet, engineerName) {
  console.log("Starting sendEmailsToEngineers function...");
  var combinedEmail = null;
  try {
    var staffSheet = SpreadsheetApp.openById(staffListSpreadsheetId).getSheetByName('All GS&O Staffs');
    if (staffSheet) {
      var lastRowStaff = staffSheet.getLastRow();
      for (var s = 2; s <= lastRowStaff; s++) {
        var staffName = staffSheet.getRange(s, 2).getValue(); // Col B: Staff Name
        if (staffName === engineerName) {
          var slackEmail = staffSheet.getRange(s, 10).getValue(); // Col J: SlackEmail
          if (slackEmail) {
            combinedEmail = slackEmail;
            console.log('Engineer', engineerName, 'found with SlackEmail:', slackEmail);
          }
          break;
        }
      }
    }
  } catch (e) {
    console.error('Error reading staff list spreadsheet:', e);
  }

  if (!combinedEmail) {
    console.error('No email found for engineer:', engineerName);
    return;
  }

  var firstName = engineerName.split(' ')[0]; // Get the first word before the first space
  var subject = "Your Assignments";
  var body = "Hi " + firstName + ",<br><br>" +
    "Please find your assigned tickets in the attached spreadsheet:<br>";

  var ss = spreadsheet; // Get the spreadsheet object
  var url = 'https://docs.google.com/feeds/download/spreadsheets/Export?key=' + ss.getId() + '&exportFormat=xlsx';

  var params = {
    method: 'get',
    headers: {
      Authorization: 'Bearer ' + ScriptApp.getOAuthToken()
    },
    muteHttpExceptions: true,
  };

  var blob = UrlFetchApp.fetch(url, params).getBlob();
  blob.setName(ss.getName() + '.xlsx');

  try {
    MailApp.sendEmail({
      to: combinedEmail,
      subject: subject,
      htmlBody: body,
      attachments: [blob]
    });
    console.log('Email sent successfully to:', combinedEmail);

  } catch (error) {
    console.error('Error sending email to:', combinedEmail, error);
  }
}

function sendGroupEmail(spreadsheet) {
  //This function will be called after all the individual emails have been sent.
  console.log("Sending group email...");

  var subject = "All Engineer Assignments";
  var body = "This is a summary of all assignments. Details for individual engineers are in the attached spreadsheet.";

  // Convert spreadsheet to Excel and attach it.  (Same as in sendEmailsToEngineers)
  var ss = spreadsheet;
  var url = 'https://docs.google.com/feeds/download/spreadsheets/Export?key=' + ss.getId() + '&exportFormat=xlsx';
  var params = {
    method: 'get',
    headers: {
      Authorization: 'Bearer ' + ScriptApp.getOAuthToken()
    },
    muteHttpExceptions: true,
  };
  var blob = UrlFetchApp.fetch(url, params).getBlob();
  blob.setName(ss.getName() + '.xlsx');

  try {
    MailApp.sendEmail({
      to: groupEmail,
      subject: subject,
      htmlBody: body,
      attachments: [blob]
    });
    console.log('Group email sent successfully to:', groupEmail);
  } catch (error) {
    console.error('Error sending group email:', error);
  }
}

function escapeSingleQuotes(str) {
  return str.replace(/'/g, "''");
}

// --- FORM SYNC CONFIG ---
// Update this to match the exact title of the question in your Google Form
var formQuestionTitle = 'Please select the Engineers on shift for ticket assignment.';

// Sync form choices from the GS&O Staff Lists spreadsheet
// Includes only rows with Team Name='Center Operations', Sub Team='IP Operations', Country='Philippines'
// Sorts names alphabetically and de-duplicates
function syncFormEngineerChoices() {
  var form;
  try {
    form = FormApp.getActiveForm();
  } catch (e) {}
  if (!form) {
    throw new Error('No active form. Bind this script to the Form project or use FormApp.openById().');
  }

  var sheet = SpreadsheetApp.openById(staffListSpreadsheetId).getSheetByName('All GS&O Staffs');
  if (!sheet) {
    throw new Error('Sheet "All GS&O Staffs" not found in staff list spreadsheet.');
  }

  var lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    throw new Error('No data rows in staff list sheet.');
  }

  // Read columns A..F (1..6): B=Staff Name, C=Team Name, E=Sub Team, F=Country
  var values = sheet.getRange(2, 1, lastRow - 1, 6).getValues();
  var namesMap = {};
  for (var i = 0; i < values.length; i++) {
    var staffName = (values[i][1] || '').toString().trim(); // B: Staff Name
    var teamName = (values[i][2] || '').toString().trim(); // C: Team Name
    var subTeam = (values[i][4] || '').toString().trim(); // E: Sub Team
    var country = (values[i][5] || '').toString().trim(); // F: Country
    
    if (staffName && 
        teamName === 'Center Operations' && 
        subTeam === 'IP Operations' && 
        country === 'Philippines') {
      namesMap[staffName] = true;
    }
  }

  var names = Object.keys(namesMap).sort(function(a, b) { return a.localeCompare(b); });
  if (names.length === 0) {
    throw new Error('No matching names (Team="Center Operations", Sub Team="IP Operations", Country="Philippines").');
  }

  var item = findFormItemByTitle_(form, formQuestionTitle);
  setChoicesForFormItem_(item, names);
}

function findFormItemByTitle_(form, title) {
  var items = form.getItems();
  for (var i = 0; i < items.length; i++) {
    if (items[i].getTitle && items[i].getTitle() === title) {
      return items[i];
    }
  }
  throw new Error('Form question titled "' + title + '" not found');
}

function setChoicesForFormItem_(item, values) {
  var type = item.getType();
  if (type === FormApp.ItemType.CHECKBOX) {
    item.asCheckboxItem().setChoiceValues(values);
  } else if (type === FormApp.ItemType.LIST) {
    item.asListItem().setChoiceValues(values);
  } else if (type === FormApp.ItemType.MULTIPLE_CHOICE) {
    item.asMultipleChoiceItem().setChoiceValues(values);
  } else {
    throw new Error('Unsupported item type: ' + type);
  }
}

// Create or refresh time-based triggers to keep the form in sync
function createSyncTriggers() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction && triggers[i].getHandlerFunction() === 'syncFormEngineerChoices') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  // Example: twice daily before shifts (adjust times as needed)
  ScriptApp.newTrigger('syncFormEngineerChoices').timeBased().atHour(7).nearMinute(50).everyDays(1).create();
  ScriptApp.newTrigger('syncFormEngineerChoices').timeBased().atHour(19).nearMinute(50).everyDays(1).create();
  // Or hourly:
  // ScriptApp.newTrigger('syncFormEngineerChoices').timeBased().everyHours(1).create();
}

// --- Assignment history helpers ---
// Ensure the history sheet exists
function getOrCreateHistorySheet_(formSpreadsheet, sheetName) {
  var sheet = formSpreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    sheet = formSpreadsheet.insertSheet(sheetName);
    sheet.appendRow(['IncidentId', 'Engineer', 'AssignedAt', 'SpreadsheetId', 'SpreadsheetUrl']);
  }
  return sheet;
}

// Load prior assignments and return a map incidentId -> engineer, limited to current shift engineers
function loadAssignmentHistory_(historySheet, currentEngineers) {
  var map = {};
  var lastRow = historySheet.getLastRow();
  if (lastRow < 2) {
    return map;
  }

  var values = historySheet.getRange(2, 1, lastRow - 1, 5).getValues();
  var engineerSet = {};
  for (var i = 0; i < currentEngineers.length; i++) {
    engineerSet[currentEngineers[i]] = true;
  }

  // Later rows override earlier ones for the same incident
  for (var j = 0; j < values.length; j++) {
    var incidentId = values[j][0];
    var engineer = values[j][1];
    if (engineerSet[engineer]) {
      map[incidentId] = engineer;
    }
  }
  return map;
}

// Append new assignments to history
function appendAssignmentHistory_(historySheet, rows) {
  if (!rows || !rows.length) {
    return;
  }
  historySheet.getRange(historySheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}

// Header helpers to tolerate changing CSV schemas
function findHeaderIndex_(headerRow, headerName) {
  var target = (headerName || '').toString().trim().toLowerCase();
  for (var i = 0; i < headerRow.length; i++) {
    var cell = (headerRow[i] || '').toString().trim().toLowerCase();
    if (cell === target) {
      return i; // zero-based index
    }
  }
  return -1;
}

function findColumnIndexByHeader_(sheet, headerName) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var idx = findHeaderIndex_(headers, headerName);
  if (idx === -1) {
    throw new Error('Header "' + headerName + '" not found on sheet "' + sheet.getName() + '".');
  }
  return idx + 1; // convert to 1-based for sheet ranges
}