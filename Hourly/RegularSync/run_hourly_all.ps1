# Simple PowerShell script to run the three hourly Jira scripts
# Used by Task Scheduler

param(
    [switch]$DryRun
)

# Set up Python path (prefer virtual environment)
$PythonPath = 'python'
$venvPath = 'G:\My Drive\Scripts\.venv\Scripts\python.exe'
if (Test-Path $venvPath) {
    $PythonPath = $venvPath
}

# Set up Google credentials if available
if (-not $env:GOOGLE_APPLICATION_CREDENTIALS) {
    $credFiles = @(
        'G:\My Drive\Scripts\jira-bigquery-key.json',
        'G:\My Drive\Scripts\service-account.json',
        'G:\My Drive\Scripts\Hourly\jira_tickets\credentials.json',
        'G:\My Drive\Scripts\Hourly\jira_comments\credentials.json',
        'G:\My Drive\Scripts\Hourly\jira_changelog\credentials.json'
    )

    foreach ($credFile in $credFiles) {
        if (Test-Path $credFile) {
            $env:GOOGLE_APPLICATION_CREDENTIALS = $credFile
            Write-Host "Using credentials: $credFile"
            break
        }
    }
}

# Define the three hourly scripts to run
$scripts = @(
    'G:\My Drive\Scripts\Hourly\jira_changelog\main.py',
    'G:\My Drive\Scripts\Hourly\jira_comments\main.py',
    'G:\My Drive\Scripts\Hourly\jira_tickets\main.py'
)

# Run each script
foreach ($script in $scripts) {
    if (-not (Test-Path $script)) {
        Write-Host "ERROR: Script not found: $script"
        continue
    }

    Write-Host "Running $script..."

    if ($DryRun) {
        Write-Host "DRYRUN: Would run: $PythonPath $script"
        continue
    }

    try {
        $scriptDir = Split-Path $script
        Push-Location $scriptDir
        & $PythonPath $script
        $exitCode = $LASTEXITCODE
        Pop-Location

        if ($exitCode -ne 0) {
            Write-Host "Script ${script} failed with exit code $exitCode"
        }
    } catch {
        Write-Host "Exception running ${script}: $_"
    }
}

Write-Host "All hourly scripts completed."
