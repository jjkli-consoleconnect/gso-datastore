# --------------------------------------
# PowerShell Script: jira_synctiertwo.ps1
# Logs Docker job status and handles retries
# --------------------------------------

$logFilePath = "G:\My Drive\Scripts\Powershell\jira_synctiertwo\jira_synctiertwo.jsonl"

function Write-Log {
    param (
        [string]$message,
        [string]$logLevel = "INFO",
        [string]$functionName = $null,
        [string]$batchID = $null,
        [string]$details = $null
    )
    # Leave Timestamp blank so BigQuery uses its default value
    $pipelineName = "jira_synctiertwo"
    $runID = $env:COMPUTERNAME + "-" + [guid]::NewGuid().ToString()
    $logObject = [PSCustomObject]@{
        Timestamp     = $null
        PipelineName  = $pipelineName
        RunID         = $runID
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



$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$dockerImages = @("jira_tiertwo", "jira_projecttracking")
$failedImages = @()

function Invoke-DockerImage {
    param (
        [string]$imageName
    )

    Write-Log "Running Docker image: $imageName" "INFO" "Invoke-DockerImage"
    try {
        & "$dockerPath" run --rm -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName 2>&1

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


Set-Location "G:\My Drive\Scripts\DockerRun"
Write-Log "Executing images: $($dockerImages -join ', ')" "INFO" "main"
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

