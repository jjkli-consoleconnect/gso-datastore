# Script to update all 24 CenterOperationsShiftSnapshotsAgg scheduled queries

$sqlFile = "g:\My Drive\Scripts\Temp\CenterOperationsShiftSnapshots_aggregated_scheduled.sql"
$sql = Get-Content -Path $sqlFile -Raw

# Get all CenterOps scheduled queries from Europe location
$allQueries = bq ls --project_id=pccw-internal-virt-agent-uat --transfer_config --transfer_location=europe --format=json | ConvertFrom-Json
$targetQueries = $allQueries | Where-Object { $_.displayName -like "CenterOps Hourly Snapshot*" } | Sort-Object displayName

Write-Host "Found $($targetQueries.Count) CenterOps Hourly Snapshot queries to update"
Write-Host ""

$successCount = 0
$failCount = 0

foreach ($query in $targetQueries) {
    $fullName = $query.name
    Write-Host "Updating: $($query.displayName) - " -NoNewline
    
    # Create params JSON - escape the SQL properly
    $sqlEscaped = $sql -replace '\\', '\\' -replace '"', '\"' -replace "`n", '\n' -replace "`r", ''
    $paramsJson = "{`"query`":`"$sqlEscaped`",`"destination_table_name_template`":`"CenterOperationsShiftSnapshotsAgg`",`"write_disposition`":`"WRITE_APPEND`"}"
    
    # Update the query
    $result = bq update `
        --transfer_config `
        --params=$paramsJson `
        $fullName 2>&1
    
    # Clean up temp file
    Remove-Item -Path $tempFile -ErrorAction SilentlyContinue
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "SUCCESS" -ForegroundColor Green
        $successCount++
    } else {
        Write-Host "FAILED" -ForegroundColor Red
        Write-Host "  Error: $result" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""
Write-Host "==================================" -ForegroundColor Cyan
Write-Host "Update Summary:" -ForegroundColor Cyan
Write-Host "  Total: $($targetQueries.Count)" -ForegroundColor Cyan
Write-Host "  Success: $successCount" -ForegroundColor Green
Write-Host "  Failed: $failCount" -ForegroundColor $(if ($failCount -gt 0) { "Red" } else { "Green" })
Write-Host "==================================" -ForegroundColor Cyan
