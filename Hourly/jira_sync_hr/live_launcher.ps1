# live_launcher.ps1
# Launcher that ensures SKIP_DOCKER is not set and runs the hourly scheduler wrapper.
# Use this in Task Scheduler to perform a real run.

# Ensure we run from the script folder
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# Remove SKIP_DOCKER if present
Remove-Item Env:SKIP_DOCKER -ErrorAction SilentlyContinue

# Optionally enable image pulling before run by setting PULL_IMAGES=1 in the scheduled task
if (-not $env:PULL_IMAGES) { $env:PULL_IMAGES = '0' }

# Run the wrapper and propagate its exit code
& 'G:\My Drive\Scripts\Hourly\jira_sync_hr\jira_sync_hr.ps1'
exit $LASTEXITCODE
