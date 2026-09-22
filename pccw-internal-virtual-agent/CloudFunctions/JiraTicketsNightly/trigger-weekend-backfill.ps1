#!/usr/bin/env pwsh
<#
.DESCRIPTION
Trigger jira-tickets-nightly backfill runs for weekend catch-up
Useful for accelerating historical data sync
#>

param(
    [int]$IntervalHours = 4,
    [int]$Runs = 6,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$FunctionUrl = "https://jira-tickets-nightly-c6zqodieea-nw.a.run.app"
$FunctionName = "jira-tickets-nightly"
$Region = "europe-west2"

function Invoke-BackfillRun {
    param([int]$RunNumber)
    
    try {
        $token = & gcloud auth print-identity-token
        $headers = @{ Authorization = "Bearer $token" }
        
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Run #$RunNumber: Triggering backfill..." -ForegroundColor Cyan
        
        if ($DryRun) {
            Write-Host "[DRY-RUN] Would invoke: POST $FunctionUrl" -ForegroundColor Yellow
            return $true
        }
        
        $resp = Invoke-WebRequest -Uri $FunctionUrl -Headers $headers -Method POST `
            -UseBasicParsing -TimeoutSec 30
        
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Run #$RunNumber: Status $($resp.StatusCode) ✓" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Run #$RunNumber: ERROR - $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Get-CurrentProgress {
    try {
        $logs = gcloud functions logs read $FunctionName --region $Region --limit 50 2>&1
        $finished = $logs | Select-String "Pipeline finished"
        if ($finished) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ✓ Previous run completed" -ForegroundColor Green
            return $true
        }
        else {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ▶ Previous run still in progress..." -ForegroundColor Yellow
            return $false
        }
    }
    catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⚠ Could not check progress: $($_.Exception.Message)" -ForegroundColor Yellow
        return $null
    }
}

Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ JiraTicketsNightly Weekend Backfill Scheduler              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

Write-Host "Schedule Summary:" -ForegroundColor Yellow
Write-Host "  Interval:       $IntervalHours hours"
Write-Host "  Planned Runs:   $Runs"
Write-Host "  Total Duration: ~$($IntervalHours * $Runs) hours"
if ($DryRun) {
    Write-Host "  Mode:           DRY-RUN (preview only)"
}
Write-Host ""

if (-not $DryRun) {
    $confirm = Read-Host "Begin scheduling $Runs runs at $IntervalHours hour intervals? (y/N)"
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host "Cancelled."
        exit 0
    }
}

Write-Host ""
Write-Host "Starting backfill schedule..." -ForegroundColor Green
Write-Host ""

$successCount = 0
$failureCount = 0

for ($i = 1; $i -le $Runs; $i++) {
    # Check if previous run finished before starting next
    if ($i -gt 1) {
        Write-Host ""
        Write-Host "Checking previous run completion..." -ForegroundColor Cyan
        $completed = $false
        while (-not $completed) {
            $result = Get-CurrentProgress
            if ($result -eq $true) {
                $completed = $true
                break
            }
            elseif ($result -eq $false) {
                Write-Host "  Waiting $IntervalHours hours before next run..."
                Start-Sleep -Seconds ($IntervalHours * 3600)
                Get-CurrentProgress
                $completed = $true
                break
            }
            else {
                # Could not check; wait interval anyway
                Write-Host "  Waiting $IntervalHours hours before next run..."
                Start-Sleep -Seconds ($IntervalHours * 3600)
                $completed = $true
            }
        }
    }
    
    # Trigger run
    $success = Invoke-BackfillRun -RunNumber $i
    if ($success) {
        $successCount++
    }
    else {
        $failureCount++
    }
    
    # Wait before next run (except on last run)
    if ($i -lt $Runs) {
        $nextRun = (Get-Date).AddHours($IntervalHours)
            Write-Host "  Next run scheduled for: $($nextRun.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Backfill Schedule Complete                                 ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "  Successful Triggers: $successCount"
Write-Host "  Failed Triggers:     $failureCount"
Write-Host ""
Write-Host "Monitor progress with:"
Write-Host "  .\monitor-backfill.ps1 -RefreshSeconds 60"
Write-Host ""
