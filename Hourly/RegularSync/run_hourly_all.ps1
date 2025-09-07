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
    # allow caller to override BaseDir; if not provided, auto-detect below
    [string]$BaseDir = $null,
    [string]$PythonPath = $null
    ,
    # When set (default), run the hourly jobs in their docker images (use :latest tags).
    [switch]$UseDocker = $true
)

Set-StrictMode -Version Latest

# Auto-normalize BaseDir: if caller didn't provide one, try to pick the repository root.
# This repo keeps an `Hourly` folder at the repository root; the script lives in
# Hourly\RegularSync, so two levels up from the script file is usually the repo root.
if ([string]::IsNullOrEmpty($BaseDir)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $candidate = Join-Path $ScriptDir '..\..'
    $resolved = $null
    try { $resolved = (Resolve-Path $candidate -ErrorAction Stop).Path } catch { $resolved = $null }
    if ($resolved -and (Test-Path (Join-Path $resolved 'Hourly'))) {
        $BaseDir = $resolved
    } else {
        # fallback to script dir if repo root not detected
        $BaseDir = $ScriptDir
    }
}

$LogDir = Join-Path $BaseDir 'Logs\Hourly'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$timestamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$mainLog = Join-Path $LogDir "run_hourly_all_$timestamp.log"

function Write-Log {
    param([string]$Text)
    $Text | Out-File -FilePath $mainLog -Append -Encoding UTF8
    # write to host (console) but do not emit to the output pipeline which callers capture
    Write-Host $Text
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

# Run a pipeline as a docker image (uses :latest images by default).
function Invoke-DockerImage {
    param([string]$ImageName)

    Write-Log "\n===== Running Docker image: $ImageName at $(Get-Date -Format o) ====="

    # Determine credential basename so it can be mounted into the container under /app
    $credBasename = $null
    if (-not [string]::IsNullOrEmpty($env:GOOGLE_APPLICATION_CREDENTIALS)) {
        $credBasename = Split-Path -Leaf $env:GOOGLE_APPLICATION_CREDENTIALS
    }

    $dockerArgs = @('--rm')
    # Mount repo root -> /app inside container so containers can read files (config.json, JQL.txt, etc.)
    $dockerArgs += "-v"; $dockerArgs += "${BaseDir}:/app"
    if ($credBasename) {
        # Forward credentials env inside container pointing to the mounted location
        $dockerArgs += "-e"; $dockerArgs += "GOOGLE_APPLICATION_CREDENTIALS=/app/$credBasename"
    }
    if (-not [string]::IsNullOrEmpty($env:LOG_LEVEL)) {
        $dockerArgs += "-e"; $dockerArgs += "LOG_LEVEL=$env:LOG_LEVEL"
    }

    $fullArgs = $dockerArgs + $ImageName

    if ($DryRun) {
        Write-Log "DRYRUN: would execute: docker $($fullArgs -join ' ')"
        return 0
    }

    try {
        & docker @($fullArgs)
        $exit = $LASTEXITCODE
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

# Edit this list if you want different scripts or order. When running via Docker
# the images below will be used (':latest' tag appended by convention).
$tasks = @(
    @{ Name = 'jira_changelog'; Script = 'Hourly\jira_changelog\main.py'; Image = 'jira_changelog_initialsync:latest' },
    @{ Name = 'jira_comments'; Script = 'Hourly\jira_comments\main.py'; Image = 'jira_comments_initialsync:latest' },
    @{ Name = 'jira_tickets'; Script = 'Hourly\jira_tickets\main.py'; Image = 'jira_tickets_initialsync:latest' }
)

$finalExit = 0
foreach ($t in $tasks) {
    if ($UseDocker) {
        # Prefer Docker image run; containers expect the repo mounted at /app
        $exit = Invoke-DockerImage $t.Image
    } else {
        $exit = Invoke-HourlyScript $t.Script
    }

    if ($exit -ne 0) {
        Write-Log "Task $($t.Name) failed with exit $exit"
        # record failure and continue so others still run
        $finalExit = $exit
    }
}

Write-Log "All done at $(Get-Date -Format o). Final exit: $finalExit"

exit $finalExit
