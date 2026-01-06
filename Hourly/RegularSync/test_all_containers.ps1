# Test script to run all three containers sequentially

Write-Host "`n=== TEST: Running all three hourly containers ===" -ForegroundColor Cyan

# Container 1: Changelog
Write-Host "`n--- Container 1: Changelog ---" -ForegroundColor Yellow
docker run --rm jira_changelog_hourly:latest
Write-Host "Changelog completed with exit code: $LASTEXITCODE" -ForegroundColor $(if ($LASTEXITCODE -eq 0) { "Green" } else { "Red" })

# Container 2: Comments  
Write-Host "`n--- Container 2: Comments ---" -ForegroundColor Yellow
docker run --rm jira_comments_hourly:latest
Write-Host "Comments completed with exit code: $LASTEXITCODE" -ForegroundColor $(if ($LASTEXITCODE -eq 0) { "Green" } else { "Red" })

# Container 3: Tickets
Write-Host "`n--- Container 3: Tickets ---" -ForegroundColor Yellow
docker run --rm jira_tickets_hourly:latest
Write-Host "Tickets completed with exit code: $LASTEXITCODE" -ForegroundColor $(if ($LASTEXITCODE -eq 0) { "Green" } else { "Red" })

Write-Host "`n=== TEST COMPLETE ===" -ForegroundColor Cyan
