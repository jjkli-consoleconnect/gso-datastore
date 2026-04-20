param(
    [switch]$AllowUnauthenticated = $false
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

$PROJECT = "pccw-internal-virt-agent-uat"
$REGION = "europe-west2"
$FUNC_NAME = "gmail-checker-oauth"
$SERVICE_ACCOUNT = "jira-bigquery@pccw-internal-virt-agent-uat.iam.gserviceaccount.com"

Write-Host "=== Deploying $FUNC_NAME ===" -ForegroundColor Cyan

# Set project
Write-Host "Setting project to $PROJECT..." -ForegroundColor Yellow
& gcloud config set project $PROJECT | Out-Null

# Deploy function (Gen2, HTTP)
Write-Host "Deploying $FUNC_NAME..." -ForegroundColor Yellow
& gcloud functions deploy $FUNC_NAME `
  --gen2 `
  --runtime python311 `
  --region $REGION `
  --source . `
  --entry-point gmail_checker_oauth `
  --trigger-http `
  --timeout 540s `
    --memory 512MB `
  --max-instances 5 `
  --service-account $SERVICE_ACCOUNT `
  $(if ($AllowUnauthenticated) {"--allow-unauthenticated"} else {"--no-allow-unauthenticated"})

if (-not $?) { 
    Pop-Location
    throw "Deployment failed for $FUNC_NAME" 
}

# Fetch URL
$URL = (& gcloud functions describe $FUNC_NAME --region $REGION --format "value(serviceConfig.uri)")
if (-not $URL) { 
    Pop-Location
    throw "Failed to fetch function URL" 
}

Write-Host ""
Write-Host "=== Deployment Complete! ===" -ForegroundColor Green
Write-Host "Function: $FUNC_NAME" -ForegroundColor White
Write-Host "Region: $REGION" -ForegroundColor White
Write-Host "URL: $URL" -ForegroundColor White
Write-Host ""
Write-Host "To invoke manually:" -ForegroundColor Cyan
Write-Host "  `$TOKEN = gcloud auth print-identity-token" -ForegroundColor Gray
Write-Host "  Invoke-WebRequest -Uri '$URL' -Headers @{ Authorization = `"Bearer `$TOKEN`" } -Method POST" -ForegroundColor Gray
Write-Host ""
Write-Host "To view logs:" -ForegroundColor Cyan
Write-Host "  gcloud functions logs read $FUNC_NAME --region=$REGION --limit=50 --project=$PROJECT" -ForegroundColor Gray

Pop-Location
