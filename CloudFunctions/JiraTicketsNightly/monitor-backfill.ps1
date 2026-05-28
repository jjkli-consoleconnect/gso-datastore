#!/usr/bin/env pwsh
<#
.DESCRIPTION
Real-time monitoring dashboard for jira-tickets-nightly backfill progress
Tracks batched processing, catch-up metrics, and completion status
#>

param(
    [int]$RefreshSeconds = 30,
    [int]$HistoryLimit = 500
)

$ErrorActionPreference = "Stop"
$FunctionName = "jira-tickets-nightly"
$Region = "europe-west2"

function Get-ProgressSummary {
    try {
        $logs = gcloud functions logs read $FunctionName --region $Region --limit $HistoryLimit 2>&1
        $output = @{
            TotalBatches = ($logs | Select-String "batch" | Measure-Object).Count
            TotalInserted = 0
            ProjectsSees = @()
            Errors = @()
            IsRunning = $null
        }
        
        # Count total rows inserted across batches
        $logs | Select-String "Inserted.*rows from batch" | ForEach-Object {
            if ($_ -match "Inserted (\d+) rows") {
                $output.TotalInserted += [int]$matches[1]
            }
        }
        
        # Get unique projects
        $logs | Select-String "catch-up:\S+" -AllMatches | ForEach-Object {
            if ($_ -match "catch-up:([^:]+)") {
                $output.ProjectsSeen += @([string]$matches[1]) | Select-Object -Unique
            }
        }
        
        # Check if running
        $finished = $logs | Select-String "Pipeline finished"
        $output.IsRunning = $null -eq $finished
        
        # Collect errors
        $logs | Select-String "ERROR|WARNING" -AllMatches | ForEach-Object {
            if ($_ -notmatch "No further window|Missing-key catch-up skipped") {
                $output.Errors += [string]$_
            }
        }
        
        return $output
    }
    catch {
        return @{
            Error = $_.Exception.Message
            IsRunning = $null
        }
    }
}

function Show-Dashboard {
    Clear-Host
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "   JiraTicketsNightly Backfill Progress Monitor" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Cyan
        Write-Host "========================================================" -ForegroundColor Cyan
        Write-Host "   JiraTicketsNightly Backfill Progress Monitor" -ForegroundColor Cyan
        Write-Host "========================================================" -ForegroundColor Cyan
    
    $summary = Get-ProgressSummary
    
    if ($summary.Error) {
        Write-Host "❌ ERROR: $($summary.Error)" -ForegroundColor Red
        return
    }
    
    # Status
    $status = if ($summary.IsRunning) { "▶️  RUNNING" } else { "⏹️  COMPLETED" }
    $statusColor = if ($summary.IsRunning) { "Green" } else { "Yellow" }
    Write-Host "Status: " -NoNewline
    Write-Host $status -ForegroundColor $statusColor
    Write-Host ""
    
    # Statistics
    Write-Host "📊 Statistics:" -ForegroundColor Yellow
    Write-Host "  Batch Chunks Processed: $($summary.TotalBatches)"
        Write-Host "  Total Rows Inserted:    $(($summary.TotalInserted).ToString("N0"))"
    Write-Host "  Projects in Progress:   $($summary.ProjectsSeen.Count)"
    Write-Host ""
    
    # Recent Projects
    if ($summary.ProjectsSeen.Count -gt 0) {
        Write-Host "🔍 Active Projects:" -ForegroundColor Yellow
        $summary.ProjectsSeen | Select-Object -Last 5 | ForEach-Object {
            Write-Host "   • $_"
        }
    }
    Write-Host ""
    
    # Recent Catch-ups
    Write-Host "📈 Recent Catch-up Summary:" -ForegroundColor Yellow
    try {
        $logs = gcloud functions logs read $FunctionName --region $Region --limit 300 2>&1
        $catchups = $logs | Select-String "Catch-up:" | Select-Object -Last 3
        if ($catchups) {
            $catchups | ForEach-Object {
                Write-Host "   $_"
            }
        }
    }
    catch {}
    Write-Host ""
    
    # Error Count
    if ($summary.Errors.Count -gt 0) {
        Write-Host "⚠️  Issues Detected: $($summary.Errors.Count)" -ForegroundColor Red
        $summary.Errors | Select-Object -Last 3 | ForEach-Object {
            Write-Host "   $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "✅ No errors detected" -ForegroundColor Green
    }
    Write-Host ""
    
    # Last refresh time
        Write-Host "Last Updated: $(Get-Date -Format 'HH:mm:ss') | Refreshing every $RefreshSeconds seconds..." -ForegroundColor DarkGray
    Write-Host "Press Ctrl+C to exit"
}

# Main loop
try {
    while ($true) {
        Show-Dashboard
        if ($RefreshSeconds -gt 0) {
            Start-Sleep -Seconds $RefreshSeconds
        }
        else {
            break
        }
    }
}
catch [OperationCanceledException] {
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "Last Updated: $timestamp | Refreshing every $RefreshSeconds seconds..." -ForegroundColor DarkGray
    Write-Host "Press Ctrl+C to exit"
}

# Main loop
try {
    while ($true) {
        Show-Dashboard
        if ($RefreshSeconds -gt 0) {
            Start-Sleep -Seconds $RefreshSeconds
        }
        else {
            break
        }
    }
}
catch {
    Write-Host "Monitoring stopped." -ForegroundColor Yellow
    exit 0
}
catch {
    Write-Host ("Error: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
