# Simple PowerShell script to run the three hourly Jira Docker containers
# Used by Task Scheduler

param(
    [switch]$DryRun
)

# No need for Python setup - using Docker containers

# Define the three Docker containers to run
$containers = @(
    'jira_changelog_hourly:latest',
    'jira_comments_hourly:latest',
    'jira_tickets_hourly:latest'
)

# Run each container
foreach ($container in $containers) {
    Write-Host "Running container $container..."

    if ($DryRun) {
        Write-Host "DRYRUN: Would run: docker run --rm $container"
        continue
    }

    try {
        & docker run --rm $container
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne 0) {
            Write-Host "Container ${container} failed with exit code $exitCode"
        }
    } catch {
        Write-Host "Exception running ${container}: $_"
    }
}

Write-Host "All hourly containers completed."