# --------------------------------------
# PowerShell Script: jira_sync_hr.ps1
# Logs Docker job status and handles retries
# --------------------------------------
[CmdletBinding()]
param()



# Use JSONL log file for BigQuery-friendly logging
$logFilePath = "G:\My Drive\Scripts\Hourly\jira_sync_hr\jira_sync_hr.jsonl"



# Consistent logging mechanism (adopted from working script)

# Human-readable console printer with colors per level
function Write-HumanLog {
    param(
        [string]$level,
        [string]$message,
        [string]$functionName
    )
    $ts = (Get-Date).ToString('HH:mm:ss')
    $prefix = "[$ts][$level]"
    if ($functionName) {
        $line = "{0} {1}: {2}" -f $prefix, $functionName, $message
    } else {
        $line = "{0}: {1}" -f $prefix, $message
    }
    switch ($level.ToUpperInvariant()) {
        'ERROR' { Write-Host $line -ForegroundColor Red; break }
        'WARN'  { Write-Host $line -ForegroundColor Yellow; break }
        'INFO'  { Write-Host $line -ForegroundColor Cyan; break }
        default { Write-Host $line }
    }
}
$global:RunID = $env:COMPUTERNAME + "-" + [guid]::NewGuid().ToString()
function Write-Log {
    param (
        [string]$message,
        [string]$logLevel = "INFO",
        [string]$functionName = $null,
        [string]$batchID = $null,
        [string]$details = $null
    )
    # Leave Timestamp blank so BigQuery uses its default value
    $pipelineName = "jira_sync_hr"
    $logObject = [PSCustomObject]@{
        Timestamp     = $null
        PipelineName  = $pipelineName
        RunID         = $global:RunID
        LogLevel      = $logLevel
        Message       = $message
        FunctionName  = $functionName
        BatchID       = $batchID
        Details       = $details
    }
    $jsonLine = $logObject | ConvertTo-Json -Compress
    # Console: human-friendly line
    Write-HumanLog -level $logLevel -message $message -functionName $functionName
    # File: structured JSONL
    Add-Content -Path $logFilePath -Value $jsonLine
}



$startTime = Get-Date

Set-Location "G:\My Drive\Scripts\Hourly"

$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$dockerImages = @("jira_tickets", "jira_comments", "jira_changelog")
$failedImages = @()
$imageRunStats = @{}

# Per-run logs directory
$logsRoot = "G:\My Drive\Scripts\Hourly\jira_sync_hr\runlogs"
New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null
$runDir = Join-Path $logsRoot $global:RunID
New-Item -ItemType Directory -Path $runDir -Force | Out-Null


function Invoke-DockerImage {
    param (
        [string]$imageName
    )

    Write-Log "Running Docker image: $imageName" "INFO" "Invoke-DockerImage"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    # Prepare env and optional mount
    $jqlDirHostPath = "G:\My Drive\Scripts\Hourly"
    $args = @("run", "--rm", "-e", "GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json", "-e", "DEBUG=false", "-e", "LOG_LEVEL=WARNING")

    # If we can read JQL.txt locally, also pass it via BASE_JQL_B64 and keep mount as a best-effort
    $jqlFile = Join-Path $jqlDirHostPath 'JQL.txt'
    if (Test-Path -LiteralPath $jqlFile) {
        try {
            $jqlContent = Get-Content -LiteralPath $jqlFile -Raw -Encoding UTF8
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($jqlContent)
            $b64 = [System.Convert]::ToBase64String($bytes)
            $args += @("-e", "BASE_JQL_B64=$b64")
            # Best-effort mount for visibility inside container as /config/JQL.txt
            $args += @("-e", "JQL_FILE=/config/JQL.txt", "-v", "${jqlDirHostPath}:/config:ro")
        } catch {
            Write-Log "Failed to read or encode JQL.txt: $_" "WARN" "Invoke-DockerImage"
        }
    } else {
        Write-Log "Shared JQL file not found at $jqlFile; relying on embedded/env defaults." "WARN" "Invoke-DockerImage"
    }

    # Append image name last
    $args += @($imageName)

    # Verbose: print the exact docker command only when -Verbose is used
    Write-Verbose ("CMD: {0} {1}" -f $dockerPath, ($args -join ' '))
    try {
        $outPath = Join-Path $runDir ("{0}.log" -f $imageName)
        Write-Verbose ("Logging container output to: {0}" -f $outPath)
    $dockerOutput = @()
    & "$dockerPath" @args 2>&1 | Tee-Object -Variable dockerOutput | Set-Content -Path $outPath

        # Detect error/warning patterns in container output for concise console surfacing
        $errLines = @($dockerOutput | Where-Object { $_ -match ' - ERROR - |Traceback|ERROR:' })
        $warnLines = @($dockerOutput | Where-Object { $_ -match ' - WARNING - ' })

        if ($LASTEXITCODE -eq 0) {
            if ($errLines.Count -gt 0) {
                Write-Log ("{0} completed with errors detected in logs (retry likely). See: {1}" -f $imageName, $outPath) "WARN" "Invoke-DockerImage"
                foreach ($l in $errLines | Select-Object -First 3) { Write-HumanLog -level 'WARN' -message $l -functionName $imageName }
            } elseif ($warnLines.Count -gt 0) {
                Write-Log ("{0} completed with warnings. See: {1}" -f $imageName, $outPath) "WARN" "Invoke-DockerImage"
                foreach ($l in $warnLines | Select-Object -First 3) { Write-HumanLog -level 'WARN' -message $l -functionName $imageName }
            } else {
                Write-Log ("{0} ran successfully. Log: {1}" -f $imageName, $outPath) "INFO" "Invoke-DockerImage"
            }
            $status = 'OK'
        } else {
            Write-Log ("❌ ERROR: {0} exited with code {1}. See: {2}" -f $imageName, $LASTEXITCODE, $outPath) "ERROR" "Invoke-DockerImage" $null $LASTEXITCODE
            foreach ($l in $errLines | Select-Object -First 10) { Write-HumanLog -level 'ERROR' -message $l -functionName $imageName }
            $script:failedImages += $imageName
            $status = 'FAIL'
        }
    } catch {
        Write-Log "❌ EXCEPTION: $imageName failed with error: $_" "ERROR" "Invoke-DockerImage" $null $_
        $script:failedImages += $imageName
        $status = 'FAIL'
    }
    finally {
        $sw.Stop()
        $imageRunStats[$imageName] = [PSCustomObject]@{
            Name        = $imageName
            Status      = $status
            DurationSec = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        }
    }
}


function Invoke-DockerImages {
    param ([string[]]$images)
    foreach ($image in $images) {
        Invoke-DockerImage -imageName $image
    }
}

Write-Log "Executing image(s): $($dockerImages -join ', ')" "INFO" "main"
foreach ($image in $dockerImages) {
    Invoke-DockerImage -imageName $image
}

if ($failedImages.Count -gt 0) {
    Write-Log "Retrying failed image(s): $($failedImages -join ', ')" "WARN" "main"
    foreach ($image in $failedImages) {
        Invoke-DockerImage -imageName $image
    }
}

if ($failedImages.Count -gt 0) {
    Write-Log "SCRIPT COMPLETED WITH FAILURES:" "ERROR" "main"
    foreach ($img in $failedImages) {
        Write-Log "  $img" "ERROR" "main"
    }
} else {
    Write-Log "SCRIPT COMPLETED SUCCESSFULLY [OK]" "INFO" "main"
}

# Print a compact summary table
Write-Host ""; Write-Host "Run summary" -ForegroundColor Green
foreach ($s in ($imageRunStats.Values | Sort-Object Name)) {
    $color = if ($s.Status -eq 'OK') { 'Green' } else { 'Red' }
    Write-Host ("- {0,-18} {1,4} in {2}s" -f $s.Name, $s.Status, $s.DurationSec) -ForegroundColor $color
}

$endTime = Get-Date
$duration = $endTime - $startTime
Write-Log "Total runtime: $($duration.TotalSeconds) seconds" "INFO" "main"