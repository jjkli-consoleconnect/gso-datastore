$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

$PROJECT = "pccw-internal-virt-agent-uat"
$REGION = "europe-west2"
$FUNC_NAME = "process-shr-people-email"
$SERVICE_ACCOUNT = "jira-bigquery@pccw-internal-virt-agent-uat.iam.gserviceaccount.com"
$TOPIC = "gmail-to-shr-people"

Write-Host "=== Deploying $FUNC_NAME ===" -ForegroundColor Cyan

& gcloud config set project $PROJECT | Out-Null

Write-Host "Deploying $FUNC_NAME..." -ForegroundColor Yellow
& gcloud functions deploy $FUNC_NAME `
  --gen2 `
  --runtime python311 `
  --region $REGION `
  --source . `
  --entry-point process_shr_people_email `
  --trigger-topic $TOPIC `
  --timeout 540s `
  --memory 512MB `
  --max-instances 1 `
  --service-account $SERVICE_ACCOUNT

if (-not $?) {
  Pop-Location
  throw "Deployment failed for $FUNC_NAME"
}

Write-Host ""
Write-Host "=== Deployment Complete! ===" -ForegroundColor Green
Write-Host "Logs: gcloud functions logs read $FUNC_NAME --region=$REGION --limit=50 --project=$PROJECT" -ForegroundColor Cyan

Pop-Location
