# create_jira_task.ps1
$taskName = 'jira_hourly'
$scriptPath = 'G:\My Drive\Scripts\Hourly\jira_sync_hr\live_launcher.ps1'
Write-Host "Creating scheduled task: $taskName -> $scriptPath"
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f $scriptPath)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Task registered. Starting task once to verify..."
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Start-Sleep -Seconds 2
    $t = Get-ScheduledTask -TaskName $taskName
    $t | Format-List | Write-Host
    Write-Host "Done. Task should start shortly (check Task Scheduler History and running processes)."
} catch {
    Write-Error "Failed to create or start task: $_"
    exit 1
}
