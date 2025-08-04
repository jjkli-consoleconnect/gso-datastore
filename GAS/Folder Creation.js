function createFoldersAndDuplicateDoc() {
  // ===== Configurable Variables =====
  var sheetName = "Sheet1"; // Change this to match your data sheet name
  var triggerSheetName = "Trigger"; // Sheet where user sets IDs
  var folderColumn = 1; // Column A for folder names
  var fileNameColumn = 2; // Column B for document names
  var jiraLinkColumn = 3; // Column C for Jira links
  var statusColumn = 4; // Column D for logging status messages
  var docLinkColumn = 5; // Column E for the created Google Doc link

  // ===== Retrieve IDs from Trigger Sheet =====
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var triggerSheet = ss.getSheetByName(triggerSheetName);
  if (!triggerSheet) {
    SpreadsheetApp.getUi().alert('Trigger sheet not found! Please create a sheet named "Trigger" with Parent Folder ID in B1 and Doc Template ID in B2.');
    return;
  }
  var parentFolderId = triggerSheet.getRange('B1').getValue();
  var docTemplateId = triggerSheet.getRange('B2').getValue();
  if (!parentFolderId || !docTemplateId) {
    SpreadsheetApp.getUi().alert('Please set Parent Folder ID in cell B1 and Doc Template ID in cell B2 of the Trigger sheet.');
    return;
  }

  // ===== Retrieve Data =====
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    SpreadsheetApp.getUi().alert('Data sheet "' + sheetName + '" not found!');
    return;
  }
  var data = sheet.getRange(2, 1, sheet.getLastRow() - 1, 3).getValues();

  var parentFolder = DriveApp.getFolderById(parentFolderId);
  var docTemplate = DriveApp.getFileById(docTemplateId);

  data.forEach(function(row, index) {
    var folderName = row[folderColumn - 1];
    var fileName = row[fileNameColumn - 1];
    var jiraLink = row[jiraLinkColumn - 1];

    // Calculate the actual row number in the sheet (data is 0-indexed, sheet starts at row 2)
    var sheetRow = index + 2;

    if (folderName && fileName) {
      try {
        // --- Folder Creation/Selection ---
        var existingFolders = parentFolder.getFolders();
        var folderExists = false;
        var targetFolder = null;

        while (existingFolders.hasNext()) {
          var existingFolder = existingFolders.next();
          if (existingFolder.getName() === folderName) {
            folderExists = true;
            targetFolder = existingFolder;
            break;
          }
        }

        if (!folderExists) {
          targetFolder = parentFolder.createFolder(folderName);
        }

        // --- Document Duplication and Editing ---
        var newDoc = docTemplate.makeCopy(fileName, targetFolder);
        var newDocId = newDoc.getId();
        var newDocUrl = newDoc.getUrl(); // Get the URL of the new document!

        var newDocFile = DocumentApp.openById(newDocId);
        var docBody = newDocFile.getBody();

        // Replace placeholders
        docBody.replaceText("<jiralink>", jiraLink || "N/A"); // Use "N/A" if jiraLink is empty
        docBody.replaceText("<folderlink>", targetFolder.getUrl());

        newDocFile.saveAndClose();

        // --- Log Success and Links in the Sheet ---
        sheet.getRange(sheetRow, statusColumn).setValue("Created ✔️");
        sheet.getRange(sheetRow, docLinkColumn).setValue(newDocUrl); // Write the document URL to Column E

      } catch (error) {
        // Log any errors
        sheet.getRange(sheetRow, statusColumn).setValue("Error ❌: " + error.message);
        // Optionally, clear the docLinkColumn if an error occurred for this row
        sheet.getRange(sheetRow, docLinkColumn).clearContent();
      }
    } else {
      // Optional: Handle empty folderName or fileName rows (e.g., skip or log)
      sheet.getRange(sheetRow, statusColumn).setValue("Skipped: Missing Folder or File Name.");
    }
  });

  SpreadsheetApp.getActiveSpreadsheet().toast("Process Completed!", "Status", 3);
}

// Add a custom menu to the Google Sheet UI
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('RunScript')
    .addItem('Create Folders and Docs', 'createFoldersAndDuplicateDoc')
    .addToUi();
}