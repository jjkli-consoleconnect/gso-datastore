function listAppsScriptProjectsInSpecificFolders() {
  var scriptFiles = [];

  // Search in the home directory
  var homeFiles = DriveApp.getRootFolder().getFiles();
  while (homeFiles.hasNext()) {
    var file = homeFiles.next();
    if (file.getMimeType() === "application/vnd.google-apps.script") {
      scriptFiles.push({ name: file.getName(), id: file.getId() });
    }
  }

  // Search in the specific folder by ID
  var folder = DriveApp.getFolderById("15Bl4YkjjIp11ZHYJA7Xszr9tnsaz64gL");
  var folderFiles = folder.getFiles();
  while (folderFiles.hasNext()) {
    var file = folderFiles.next();
    if (file.getMimeType() === "application/vnd.google-apps.script") {
      scriptFiles.push({ name: file.getName(), id: file.getId() });
    }
  }

  Logger.log(scriptFiles);
}