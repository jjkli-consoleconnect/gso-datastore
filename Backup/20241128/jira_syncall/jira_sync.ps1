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

# Function to run a Docker image
function Invoke-DockerImage {
    param (
        [string]$imageName
    )

    Write-Log "Starting Docker image $imageName."
    try {
        $output = docker run -e GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json" $imageName 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Docker image $imageName ran successfully."
            # Extract and log additional details from the output
            if ($output -match "Rows pulled: (\d+)") {
                $rowsPulled = $matches[1]
                Write-Log "Rows pulled from JIRA: $rowsPulled"
            }
            if ($output -match "Rows merged: (\d+)") {
                $rowsMerged = $matches[1]
                Write-Log "Rows merged successfully: $rowsMerged"
            }
        } else {
            Write-Log "Error running Docker image $imageName. Output: $output"
            $failedImages += $imageName
        }
    } catch {
        Write-Log "Exception running Docker image $imageName. $_"
        $failedImages += $imageName
    }
}

# Function to process Docker images
function Invoke-DockerImages {
    param (
        [array]$images
    )

    if ($images.Count -eq 0) {
        Write-Log "No Docker images to process."
        return
    }

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