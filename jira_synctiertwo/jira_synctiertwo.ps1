# --------------------------------------
# PowerShell Script: jira_synctiertwo.ps1
# Logs Docker job status and handles retries
# --------------------------------------

$logFilePath = "G:\My Drive\Scripts\jira_synctiertwo\jira_synctiertwo.log"

function Write-Log {
    param ([string]$message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    Write-Output $logMessage
    Add-Content -Path $logFilePath -Value $logMessage
}

Write-Log "========================================="
Write-Log "SCRIPT EXECUTION STARTED"
Write-Log "========================================="

$startTime = Get-Date

Set-Location "G:\My Drive\Scripts\jira_syncall"

$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$dockerImages = @("jira_tiertwo")
$failedImages = @()

function Invoke-DockerImage {
    param ([string]$imageName)

    Write-Log "Running Docker image: $imageName"

    try {
        $output = & "$dockerPath" run -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName 2>&1

        if ($LASTEXITCODE -eq 0) {
            Write-Log "$imageName ran successfully."
            
        } else {
            Write-Log "❌ ERROR: $imageName exited with code $LASTEXITCODE."
            $script:failedImages += $imageName
        }
    } catch {
        Write-Log "❌ EXCEPTION: $imageName failed with error: $_"
        $script:failedImages += $imageName
    }
}

function Invoke-DockerImages {
    param ([string[]]$images)
    foreach ($image in $images) {
        Invoke-DockerImage -imageName $image
    }
}

Write-Log "Executing image(s): $($dockerImages -join ', ')"
Invoke-DockerImages -images $dockerImages

if ($failedImages.Count -gt 0) {
    Write-Log "Retrying failed image(s): $($failedImages -join ', ')"
    Invoke-DockerImages -images $failedImages
}

if ($failedImages.Count -gt 0) {
    Write-Log "SCRIPT COMPLETED WITH FAILURES:"
    foreach ($img in $failedImages) {
        Write-Log "  ❌ $img"
    }
} else {
    Write-Log "SCRIPT COMPLETED SUCCESSFULLY ✅"
}

$endTime = Get-Date
$duration = $endTime - $startTime
Write-Log "Total runtime: $($duration.TotalSeconds) seconds"

Write-Log "========================================="
Write-Log "SCRIPT EXECUTION ENDED"
Write-Log "=========================================`n"