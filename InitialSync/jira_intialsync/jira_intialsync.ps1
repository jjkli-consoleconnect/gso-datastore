# --------------------------------------
# PowerShell Script: jira_sync_initialsync.ps1
# Logs Docker job status and handles retries
# --------------------------------------



# Use JSONL log file for BigQuery-friendly logging
$logFilePath = "G:\My Drive\Scripts\InitialSync\jira_intialsync\jira_intialsync.jsonl"



# Consistent logging mechanism (adopted from working script)
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
    $pipelineName = "jira_sync_initialsync"
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
    Write-Output $jsonLine
    Add-Content -Path $logFilePath -Value $jsonLine
}



$startTime = Get-Date

Set-Location "G:\My Drive\Scripts\InitialSync"

$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$dockerImages = @("jira_tickets_initialsync", "jira_comments_initialsync", "jira_changelog_initialsync")
$failedImages = @()


function Invoke-DockerImage {
    param (
        [string]$imageName
    )

    Write-Log "Running Docker image: $imageName" "INFO" "Invoke-DockerImage"
    # Print the actual Docker command for debugging
    $dockerCmd = '$dockerPath run --rm -v "G:\My Drive\Scripts\InitialSync\' + $imageName + ':/app" -e GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json ' + $imageName
    Write-Output "CMD: $dockerCmd"
    try {
        & "$dockerPath" run --rm -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName

        if ($LASTEXITCODE -eq 0) {
            Write-Log "$imageName ran successfully." "INFO" "Invoke-DockerImage"
        } else {
            Write-Log "❌ ERROR: $imageName exited with code $LASTEXITCODE." "ERROR" "Invoke-DockerImage" $null $LASTEXITCODE
            $script:failedImages += $imageName
        }
    } catch {
        Write-Log "❌ EXCEPTION: $imageName failed with error: $_" "ERROR" "Invoke-DockerImage" $null $_
        $script:failedImages += $imageName
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
        Write-Log "  ❌ $img" "ERROR" "main"
    }
} else {
    Write-Log "SCRIPT COMPLETED SUCCESSFULLY ✅" "INFO" "main"
}

$endTime = Get-Date
$duration = $endTime - $startTime
Write-Log "Total runtime: $($duration.TotalSeconds) seconds" "INFO" "main"