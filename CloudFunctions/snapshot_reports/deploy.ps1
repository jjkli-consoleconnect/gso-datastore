$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

$PROJECT = "pccw-internal-virt-agent-uat"
$REGION = "europe-west2"
$FUNC_NAME = "process-snapshot-reports-email"
$SERVICE_ACCOUNT = "14417857267-compute@developer.gserviceaccount.com"
$TOPIC = "gmail-snapshot-reports"

Write-Host "=== Deploying $FUNC_NAME ===" -ForegroundColor Cyan

# Set project
Write-Host "Setting project to $PROJECT..." -ForegroundColor Yellow
& gcloud config set project $PROJECT | Out-Null

# Create Pub/Sub topic if it doesn't exist
Write-Host "Ensuring Pub/Sub topic exists: $TOPIC" -ForegroundColor Yellow
$topicCheck = & gcloud pubsub topics describe $TOPIC --project=$PROJECT 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Creating topic..." -ForegroundColor Yellow
    & gcloud pubsub topics create $TOPIC --project=$PROJECT
    Write-Host "  Topic created" -ForegroundColor Green
} else {
    Write-Host "  Topic already exists" -ForegroundColor Gray
}

# Deploy function
Write-Host "Deploying $FUNC_NAME..." -ForegroundColor Yellow
& gcloud functions deploy $FUNC_NAME `
  --gen2 `
  --runtime python311 `
  --region $REGION `
  --source . `
  --entry-point process_snapshot_report `
  --trigger-topic $TOPIC `
  --timeout 540s `
    --memory 256MB `
  --service-account $SERVICE_ACCOUNT `
  --project $PROJECT

if (-not $?) { 
    Pop-Location
    throw "Deployment failed for $FUNC_NAME" 
}

Write-Host ""
Write-Host "=== Deployment Complete! ===" -ForegroundColor Green
Write-Host "Function: $FUNC_NAME" -ForegroundColor White
Write-Host "Region: $REGION" -ForegroundColor White  
Write-Host "Trigger: Pub/Sub topic '$TOPIC'" -ForegroundColor White
Write-Host ""
Write-Host "To test, trigger gmail_checker or publish directly:" -ForegroundColor Cyan
Write-Host "  gcloud pubsub topics publish gmail-checker-trigger --message='{\"trigger\":\"manual\"}' --project=$PROJECT" -ForegroundColor Gray
Write-Host ""
Write-Host "To view logs:" -ForegroundColor Cyan
Write-Host "  gcloud functions logs read $FUNC_NAME --region=$REGION --limit=50 --project=$PROJECT" -ForegroundColor Gray

Pop-Location
