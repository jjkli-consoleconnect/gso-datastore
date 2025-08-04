Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -ExecutionPolicy Bypass -NoProfile -File ""G:\My Drive\Scripts\Hourly\jira_sync_hr\jira_sync_hr.ps1""", 7, False