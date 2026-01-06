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
    Write-Host "`n=== Running container $container ===" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host "DRYRUN: Would run: docker run --rm $container"
        continue
    }

    try {
        Write-Host "Executing: docker run --rm $container" -ForegroundColor Gray
        & docker run --rm $container
        $exitCode = $LASTEXITCODE
        Write-Host "Container ${container} exited with code: $exitCode" -ForegroundColor Gray

        if ($exitCode -ne 0) {
            Write-Host "Container ${container} failed with exit code $exitCode - continuing to next container..." -ForegroundColor Yellow
        } else {
            Write-Host "Container ${container} completed successfully" -ForegroundColor Green
        }
    } catch {
        Write-Host "Exception running ${container}: $_" -ForegroundColor Red
    }
    
    Write-Host "Finished processing $container, moving to next..." -ForegroundColor Gray
}

Write-Host "All hourly containers completed."