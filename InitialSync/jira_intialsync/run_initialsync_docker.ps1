# Simple PowerShell script to run Jira initial sync containers
# Used by Task Scheduler
# Modified for local machine with built-in credentials

$images = @("jira_tickets_initialsync", "jira_comments_initialsync", "jira_changelog_initialsync")

foreach ($image in $images) {
    Write-Host "Running $image..."
    try {
        & docker run --rm $image
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Host "Container ${image} failed with exit code $exitCode"
        }
    } catch {
        Write-Host "Exception running ${image}: $_"
    }
}

Write-Host "All initial sync containers completed."