# debug_scheduler_launcher.ps1
# Runs the scheduler wrapper in safe simulation mode and captures output to a log for troubleshooting.
$log = 'G:\My Drive\Scripts\Hourly\jira_sync_hr\scheduler_debug.log'
"=== Launcher start $(Get-Date) ===" | Out-File -FilePath $log -Encoding UTF8 -Append
# Force simulation mode so we don't start containers
$env:SKIP_DOCKER = '1'
# Ensure cwd
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Definition)
# Run the wrapper and capture output + exit code
& 'G:\My Drive\Scripts\Hourly\jira_sync_hr\jira_sync_hr.ps1' *>&1 | Out-File -FilePath $log -Encoding UTF8 -Append
"=== Launcher exitcode: $LASTEXITCODE ===" | Out-File -FilePath $log -Encoding UTF8 -Append
exit $LASTEXITCODE
