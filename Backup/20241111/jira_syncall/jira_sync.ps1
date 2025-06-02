# Define log file path
$logFilePath = "C:\Users\jjkli\Scripts\jira_syncall\jira_sync.log"

# Function to write log
function Write-Log {
    param (
        [string]$message
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    Add-Content -Path $logFilePath -Value $logMessage
    Write-Host $logMessage
}

# Define Docker images
$dockerImages = @("jira_projecttracking", "jira_secondtier", "jira_ccas", "jira_ccprov")

# Define a list to hold failed images
$failedImages = @()

# Function to run a Docker image
function Run-DockerImage {
    param (
        [string]$imageName
    )

    try {
        Write-Log "Running Docker image: $imageName"
        docker run -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName
        Write-Log "Docker image $imageName ran successfully."
    } catch {
        Write-Log "Error running Docker image $imageName. Adding to failed list."
        $failedImages += $imageName
    }
}

# Function to process Docker images
function Process-DockerImages {
    param (
        [array]$images
    )

    foreach ($image in $images) {
        Run-DockerImage -imageName $image
    }
}

# Start logging
Write-Log "Starting to process Docker images."

# Run each Docker image
Process-DockerImages -images $dockerImages

# Retry failed images
if ($failedImages.Count -gt 0) {
    Write-Log "Retrying failed Docker images..."
    Process-DockerImages -images $failedImages
}

# End logging
Write-Log "All Docker images have been processed."
