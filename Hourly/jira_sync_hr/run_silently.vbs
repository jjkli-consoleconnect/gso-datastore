Set objShell = CreateObject("WScript.Shell")

' full path to powershell to avoid PATH issues
psPath = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
scriptPath = "G:\\My Drive\\Scripts\\Hourly\\jira_sync_hr\\jira_sync_hr.ps1"

' Optionally set environment for child process (uncomment for dry-run testing)
' objShell.Environment("Process")("SKIP_DOCKER") = "1"

' Ensure the process runs from the script folder (helps when Task Scheduler uses a different cwd)
objShell.CurrentDirectory = "G:\\My Drive\\Scripts\\Hourly\\jira_sync_hr"

' Build command and run hidden (0). Do not wait for completion (False).
cmd = Chr(34) & psPath & Chr(34) & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & scriptPath & Chr(34)
objShell.Run cmd, 0, False