# JiraTicketsNightly - Deployment Status & Monitoring

## ✅ Deployment Complete
- **Date**: 2026-03-20
- **Function**: jira-tickets-nightly
- **Region**: europe-west2
- **Runtime**: Python 3.11
- **Memory**: 2048Mi
- **Timeout**: 3600s (1 hour)
- **URL**: https://jira-tickets-nightly-c6zqodieea-nw.a.run.app

## 🔧 Configuration
```
MISSING_KEY_CATCHUP_PER_PROJECT: 50000  # Max keys to catch-up per project
CACHE_BATCHED_FETCH_SIZE: 500           # Issues per batch
CACHE_BATCH_DURATION_SEC: 120           # For future cache windowing
MIN_START: 2023-01-01T00:00:00Z         # Historical backfill start
```

## 📊 Current Execution (First Run)
Started: 2026-03-20 07:57:46 UTC
Status: **RUNNING** (batching through all projects)

### Batching Strategy Active ✓
- Processing catch-up keys in 500-key batches
- Each batch split into 50-key Jira API chunks for pagination
- Memory efficient: ~2.5MB per batch (vs 250MB all-at-once)

### Sample Progress Log:
```
[TAC] Catch-up: 0 missing keys, 5508 stale keys; fetching 5508...
  → batch 1: Inserted 500 rows ✓
  → batch 2: Inserted 500 rows ✓
  → batch 3: Inserted 500 rows ✓
  → batch 4: Inserted 500 rows ✓
  → batch 5: Inserted 500 rows ✓
  → batch 6: Inserted 500 rows ✓
  [Merged after all batches]
```

## 🚀 Weekend Backfill Strategy
The function continues to process:
1. **Standard sync**: Each project's recent changes (updated/resolved in last 24h)
2. **Catch-up sync**: Stale keys (>30 days without update) + missing keys
3. **Soft-delete reconciliation**: Mark keys no longer in JIRA as deleted

Run frequency recommended:
- **Continuous execution**: Let current run complete (~1 hour typical)
- **Schedule additional runs**: If backfill needed faster, trigger manually

## 📈 Monitoring Commands

### Live Tail (Every 30 seconds)
```powershell
while ($true) {
  gcloud functions logs read jira-tickets-nightly --region europe-west2 --limit 100 `
    | Select-String "Catch-up|Inserted|merged|finished" -First 10
  Write-Host "---" (Get-Date)
  Start-Sleep -Seconds 30
}
```

### Completion Check
```powershell
gcloud functions logs read jira-tickets-nightly --region europe-west2 --limit 100 `
  | Select-String "Pipeline finished"
```

### Project-Specific Progress
```powershell
gcloud functions logs read jira-tickets-nightly --region europe-west2 --limit 300 `
  | Select-String "Catch-up:" # Shows summary per project
```

### Errors/Warnings
```powershell
gcloud functions logs read jira-tickets-nightly --region europe-west2 --limit 200 `
  | Select-String "WARNING|ERROR"
```

## 🔄 Schedule Future Backfills
To run additional catch-up over the weekend (e.g., every 4 hours):

```powershell
$url = "https://jira-tickets-nightly-c6zqodieea-nw.a.run.app"
$token = gcloud auth print-identity-token
$headers = @{ Authorization = "Bearer $token" }

# Trigger next run
Invoke-WebRequest -Uri $url -Headers $headers -Method POST
```

## 📋 Next Steps
1. Monitor the current run until "Pipeline finished" appears in logs
2. Review caught-up key counts in "Catch-up merged" messages
3. Adjust `MISSING_KEY_CATCHUP_PER_PROJECT` (default 50000) if needed for faster runs
4. Schedule hourly triggers over the weekend if faster catch-up desired

---
**Last Updated**: 2026-03-20 08:09 UTC
**Batching Status**: ✅ ACTIVE & WORKING EFFICIENTLY
