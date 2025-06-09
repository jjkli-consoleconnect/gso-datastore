# Define the log file path
$logFilePath = "C:\Users\jjkli\Scripts\jira_syncall\jira_sync.log"

# Function to log messages with timestamps
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    Write-Output $logMessage
    Add-Content -Path $logFilePath -Value $logMessage
}

# Log environment variables
Get-ChildItem Env: | ForEach-Object { Write-Log "$($_.Name)=$($_.Value)" }

# Set working directory
Set-Location "C:\Users\jjkli\Scripts\jira_syncall"

# Full path to docker executable
$dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"

# Function to run a Docker image
function Invoke-DockerImage {
    param (
        [string]$imageName
    )

    Write-Log "Starting Docker image $imageName."
    try {
        $output = & "$dockerPath" run -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Docker image $imageName ran successfully."
            # Extract and log additional details from the output
            if ($output -match "Pulled (\d+) lines from Jira.") {
                $pulledLines = $matches[1]
                Write-Log "Docker image $imageName pulled $pulledLines lines from Jira."
            }
            if ($output -match "Merged (\d+) lines into BigQuery.") {
                $mergedLines = $matches[1]
                Write-Log "Docker image $imageName merged $mergedLines lines into BigQuery."
            }
        } else {
            Write-Log "Docker image $imageName failed with exit code $LASTEXITCODE."
            $script:failedImages += $imageName
        }
    } catch {
        Write-Log "Docker image $imageName encountered an error: $_"
        $script:failedImages += $imageName
    }
}

function Invoke-DockerImages {
    param (
        [string[]]$images
    )
    foreach ($image in $images) {
        Invoke-DockerImage -imageName $image
    }
}

# Initialize Docker images array
$dockerImages = @("jira_projecttracking", "jira_ccas", "jira_ccprov", "jira_secondtier")  # Replace with your actual Docker images
$failedImages = @()

# Start logging
Write-Log "Starting to process Docker images."

# Run each Docker image
Invoke-DockerImages -images $dockerImages

# Retry failed images
if ($failedImages.Count -gt 0) {
    Write-Log "Retrying failed Docker images..."
    Invoke-DockerImages -images $failedImages
}

# End logging
Write-Log "All Docker images have been processed."