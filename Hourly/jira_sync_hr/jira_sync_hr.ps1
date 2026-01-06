# Minimal scheduler-friendly wrapper: run three docker images (or simulate with SKIP_DOCKER=1)
# This file intentionally minimal so Task Scheduler only queues containers.
[CmdletBinding()]
param()

# Ensure we run from the script directory (Task Scheduler often uses SYSTEM cwd)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $scriptDir -or -not (Test-Path -LiteralPath $scriptDir)) { $scriptDir = (Get-Location).Path }
Set-Location -LiteralPath $scriptDir

# Images to run (use the hourly builds which are newer on the host)
$images = @('jira_tickets:latest', 'jira_comments:latest', 'jira_changelog:latest')

# Find docker executable: prefer bundled path, otherwise rely on PATH
$dockerCandidate = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
if (Test-Path -LiteralPath $dockerCandidate) { $dockerPath = $dockerCandidate } else { $dockerPath = 'docker' }

Write-Host "[INFO] Starting scheduler wrapper in: $scriptDir"
Write-Host "[INFO] Docker command: $dockerPath"
if ($env:SKIP_DOCKER -eq '1') { Write-Host "[INFO] SKIP_DOCKER=1 -> simulation mode (no containers will be started)" }

$overallFailed = $false
foreach ($img in $images) {
    Write-Host "---"; Write-Host "[INFO] Invoking: $img"
    # Resolve and print the exact image ID we will run (helps detect mismatched tags vs images)
    try {
        $imgId = & $dockerPath image inspect --format '{{.Id}}' $img 2>$null
        if ($LASTEXITCODE -eq 0 -and $imgId) {
            Write-Host ("[INFO] Resolved image ID for {0}: {1}" -f $img, $imgId)
        } else {
            Write-Host ("[WARN] Could not resolve local image ID for {0} (image may be absent locally)" -f $img)
        }
    } catch {
        Write-Host ("[WARN] Error resolving image ID for {0}: {1}" -f $img, $_)
    }

    # Optionally pull latest image before running when env PULL_IMAGES=1 (useful for deployments)
    if ($env:PULL_IMAGES -eq '1') {
        Write-Host "[INFO] PULL_IMAGES=1 -> pulling latest for $img"
        & $dockerPath pull $img 2>&1 | ForEach-Object { $_ }
        if ($LASTEXITCODE -ne 0) { Write-Host "[WARN] Pull failed for $img with exit $LASTEXITCODE" -ForegroundColor Yellow }
    }
    if ($env:SKIP_DOCKER -eq '1') {
        Write-Host "[SIM] Would run: $dockerPath run --rm $img"
        continue
    }

    try {
        # Run container and stream logs; if you need to pass env or mounts, keep this simple wrapper and configure images
        & $dockerPath run --rm $img 2>&1 | ForEach-Object { $_ }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] $img exited with code $LASTEXITCODE" -ForegroundColor Red
            $overallFailed = $true
        } else {
            Write-Host "[OK] $img completed" -ForegroundColor Green
        }
    } catch {
        Write-Host ("[EXCEPTION] running {0}: {1}" -f $img, $_) -ForegroundColor Red
        $overallFailed = $true
    }
}

if ($overallFailed) {
    Write-Host "[ERROR] One or more images failed"
    exit 1
} else {
    Write-Host "[INFO] All images completed (or simulated)"
    exit 0
}