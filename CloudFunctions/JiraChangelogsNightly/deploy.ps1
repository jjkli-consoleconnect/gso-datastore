param(
    [switch]$AllowUnauthenticated = $true,
    [string]$Environment = "uat"
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

if ($Environment -eq "prod") {
    $PROJECT = "pccw-internal-virtual-agent"
    $REGION = "europe-west2"
    $CONNECTOR = "eu-prod-wanda-vpc-conn"
    $FUNC_NAME = "jira-changelogs-nightly"
    $SERVICE_ACCOUNT = "370161436243-compute@developer.gserviceaccount.com"
} else {
    $PROJECT = "pccw-internal-virt-agent-uat"
    $REGION = "us-central1"
    $CONNECTOR = $null
    $FUNC_NAME = "JiraChangelogsNightly"
    $SERVICE_ACCOUNT = $null
}

Write-Host "Deploying $FUNC_NAME to project $PROJECT region $REGION"

& gcloud config set project $PROJECT | Out-Null

$deployArgs = @(
    "functions", "deploy", $FUNC_NAME,
    "--gen2",
    "--runtime", "python311",
    "--region", $REGION,
    "--source", ".",
    "--entry-point", "main",
    "--trigger-http",
    "--timeout", "3600s",
    "--memory", "2048Mi",
    "--max-instances", "5"
)

if ($CONNECTOR) {
    $deployArgs += "--vpc-connector"
    $deployArgs += "projects/$PROJECT/locations/$REGION/connectors/$CONNECTOR"
    $deployArgs += "--egress-settings"
    $deployArgs += "all"
}

if ($SERVICE_ACCOUNT) {
    $deployArgs += "--service-account"
    $deployArgs += $SERVICE_ACCOUNT
}

if ($AllowUnauthenticated) {
    $deployArgs += "--allow-unauthenticated"
} else {
    $deployArgs += "--no-allow-unauthenticated"
}

& gcloud @deployArgs
if (-not $?) { Pop-Location; throw "Deployment failed for $FUNC_NAME" }

$URL = (& gcloud functions describe $FUNC_NAME --region $REGION --format "value(serviceConfig.uri)")
if (-not $URL) { throw "Failed to fetch function URL" }
Write-Host "Function URL: $URL"

$TOKEN = (& gcloud auth print-identity-token)
Write-Host "Invoking $FUNC_NAME..."
$resp = Invoke-WebRequest -Uri $URL -Headers @{ Authorization = "Bearer $TOKEN" } -Method POST -UseBasicParsing
Write-Host "Response status: $($resp.StatusCode)"
Write-Host "Body: $($resp.Content)"
Pop-Location
