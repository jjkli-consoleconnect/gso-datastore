<#
run_hourly_all.ps1

Runs the repository's three hourly scripts in sequence with logging.

Assumptions:
- The three scripts are located in the same folder as this file:
  - run_hourly_changelog.ps1
  - run_hourly_comments.ps1
  - run_hourly_tickets.ps1
- If you want a different set, edit the $scripts array below.
#>

param(
    [switch]$DryRun,
    [string]$BaseDir = (Split-Path -Parent $MyInvocation.MyCommand.Definition),
    [string]$PythonPath = $null
)

Set-StrictMode -Version Latest

$LogDir = Join-Path $BaseDir 'Logs\Hourly'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$timestamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$mainLog = Join-Path $LogDir "run_hourly_all_$timestamp.log"

function Write-Log {
    param([string]$Text)
    $Text | Out-File -FilePath $mainLog -Append -Encoding UTF8
    Write-Output $Text
}

function Invoke-HourlyScript {
    param([string]$RelPath)

    $candidate = Join-Path $BaseDir $RelPath
    if (-not (Test-Path $candidate)) {
        Write-Log "ERROR: script not found: $candidate"
        return 2
    }

    Write-Log "\n===== Running: $candidate at $(Get-Date -Format o) ====="

    # pick python: use provided PythonPath, else .venv python, else 'python' in PATH
    $py = $PythonPath
    if ([string]::IsNullOrEmpty($py)) {
        $venv = Join-Path $BaseDir '.venv\Scripts\python.exe'
        if (Test-Path $venv) { $py = $venv } else { $py = 'python' }
    }

    if ($DryRun) {
        Write-Log "DRYRUN: would execute: \"$py\" \"$candidate\" (cwd: \"$(Split-Path $candidate)\")"
        return 0
    }

    try {
        $wd = Split-Path $candidate
        Push-Location $wd
        try {
            & "$py" "$candidate"
            $exit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Write-Log "Exit code: $exit"
        return $exit
    } catch {
        Write-Log "EXCEPTION: $_"
        return 1
    }
}

# Auto-detect Google application credentials if not already set
if (-not [string]::IsNullOrEmpty($env:GOOGLE_APPLICATION_CREDENTIALS)) {
    Write-Log "GOOGLE_APPLICATION_CREDENTIALS already set to: $env:GOOGLE_APPLICATION_CREDENTIALS"
} else {
    $childNames = @(
        'jira-bigquery-key.json',
        'service-account.json',
        'service_account_env.py',
        'Hourly\jira_tickets\credentials.json',
        'Hourly\jira_comments\credentials.json',
        'Hourly\jira_changelog\credentials.json'
    )
    $candidates = $childNames | ForEach-Object { Join-Path $BaseDir $_ }
    $found = $null
    foreach ($c in $candidates) {
        if ($null -ne $c -and (Test-Path $c)) { $found = $c; break }
    }
    if ($found) {
        $env:GOOGLE_APPLICATION_CREDENTIALS = $found
        Write-Log "Set GOOGLE_APPLICATION_CREDENTIALS -> $found"
    } else {
        Write-Log "No Google credentials found in known locations; child scripts may error if they require ADC."
    }
}

# Edit this list if you want different scripts or order
$scripts = @(
    'Hourly\jira_changelog\main.py',
    'Hourly\jira_comments\main.py',
    'Hourly\jira_tickets\main.py'
)

$finalExit = 0
foreach ($s in $scripts) {
    $exit = Invoke-HourlyScript $s
    if ($exit -ne 0) {
        Write-Log "Script $s failed with exit $exit"
        # record failure and continue so others still run
        $finalExit = $exit
    }
}

Write-Log "All done at $(Get-Date -Format o). Final exit: $finalExit"

exit $finalExit
