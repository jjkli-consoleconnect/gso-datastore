param(
  [switch]$AllowUnauthenticated
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
$PROJECT = "pccw-internal-virtual-agent"
$REGION = "europe-west2"
$CONNECTOR = "eu-prod-wanda-vpc-conn"
$FUNC_NAME = "jira-tickets-nightly"
$SERVICE_ACCOUNT = "370161436243-compute@developer.gserviceaccount.com"

if (-not $PSBoundParameters.ContainsKey('AllowUnauthenticated')) {
  $AllowUnauthenticated = $true
}

Write-Host "Deploying $FUNC_NAME to project $PROJECT region $REGION"

# Ensure project
& gcloud config set project $PROJECT | Out-Null

# Deploy function (Gen2, HTTP)
& gcloud functions deploy $FUNC_NAME `
  --gen2 `
  --runtime python311 `
  --region $REGION `
  --source . `
  --entry-point main `
  --trigger-http `
  --timeout 3600s `
  --memory 2048Mi `
  --max-instances 5 `
  --vpc-connector "projects/$PROJECT/locations/$REGION/connectors/$CONNECTOR" `
  --egress-settings all `
  --service-account $SERVICE_ACCOUNT `
  --set-env-vars "MISSING_KEY_CATCHUP_PER_PROJECT=50000,MIN_START=2023-01-01T00:00:00Z" `
  $(if ($AllowUnauthenticated) {"--allow-unauthenticated"} else {"--no-allow-unauthenticated"})

$LASTEXITCODE = $?
if (-not $LASTEXITCODE) { Pop-Location; throw "Deployment failed for $FUNC_NAME" }

# Fetch URL
$URL = (& gcloud functions describe $FUNC_NAME --region $REGION --format "value(serviceConfig.uri)")
if (-not $URL) { throw "Failed to fetch function URL" }
Write-Host "Function URL: $URL"

# Invoke once with identity token
$TOKEN = (& gcloud auth print-identity-token)
Write-Host "Invoking $FUNC_NAME..."
$resp = Invoke-WebRequest -Uri $URL -Headers @{ Authorization = "Bearer $TOKEN" } -Method POST -UseBasicParsing
Write-Host "Response status: $($resp.StatusCode)"
Write-Host "Body: $($resp.Content)"
Pop-Location
