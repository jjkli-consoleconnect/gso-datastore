$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir

$PROJECT    = "pccw-internal-virtual-agent"
$REGION     = "europe-west2"
$CONNECTOR  = "eu-prod-wanda-vpc-conn"
$FUNC_NAME  = "jira-delete-reconciliation"
$SA         = "370161436243-compute@developer.gserviceaccount.com"
# Toggle these flags as needed for manual deploy testing.
$dryRunEnabled = $true
$disableUnauth = $false
$dryRunEnvValue = if ($dryRunEnabled) { "true" } else { "false" }

# Fast test profile guidance:
# - smoke: single project, low candidate cap for quick validation.
# - full: all projects with production-like limits.
$deployProfile = "full"   # valid: "smoke", "full"

$staleDays = 0
$countGateRatio = "0.70"
$rateLimitPerSec = 30
$concurrentRequests = 10
$maxCandidatesPerProject = 500
$singleProject = ""

if ($deployProfile -eq "smoke") {
    # Keep smoke mode available for targeted validation on one project.
    $singleProject = "Mobility SMS - CE"
    # SMSCE has confirmed historical drift between Jira and BQ counts.
    # Lowering the gate for this smoke run allows per-key 404 proof to drive deletes.
    $countGateRatio = "0.30"
    $staleDays = 0
    $maxCandidatesPerProject = 50
    $concurrentRequests = 6
    $rateLimitPerSec = 20
}

$envVars = @(
    "DRY_RUN=$dryRunEnvValue",
    "STALE_DAYS=$staleDays",
    "COUNT_GATE_RATIO=$countGateRatio",
    "MAX_CANDIDATES_PER_PROJECT=$maxCandidatesPerProject",
    "RATE_LIMIT_PER_SEC=$rateLimitPerSec",
    "CONCURRENT_REQUESTS=$concurrentRequests"
)
if ($singleProject) {
    $envVars += "SINGLE_PROJECT=$singleProject"
}
$envVarsArg = ($envVars -join ",")

Write-Host "Profile: $deployProfile"
Write-Host "Dry run: $dryRunEnvValue"
Write-Host "Single project: $(if ($singleProject) { $singleProject } else { '<all>' })"
Write-Host "Max candidates/project: $maxCandidatesPerProject"

Write-Host "Deploying $FUNC_NAME to $PROJECT / $REGION"
& gcloud config set project $PROJECT | Out-Null

& gcloud functions deploy $FUNC_NAME `
  --gen2 `
  --runtime python311 `
  --region $REGION `
  --source . `
  --entry-point main `
  --trigger-http `
  --timeout 1800s `
  --memory 512Mi `
  --max-instances 1 `
  --vpc-connector "projects/$PROJECT/locations/$REGION/connectors/$CONNECTOR" `
  --egress-settings all `
  --service-account $SA `
    --set-env-vars $envVarsArg `
    $(if ($disableUnauth) {"--no-allow-unauthenticated"} else {"--allow-unauthenticated"})

if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Deployment failed" }

$URL   = (& gcloud functions describe $FUNC_NAME --region $REGION --format "value(serviceConfig.uri)")
$TOKEN = (& gcloud auth print-identity-token)

Write-Host ""
Write-Host "Function URL: $URL"
Write-Host ""

if ($dryRunEnabled) {
    Write-Host "Invoking in DRY RUN mode (no BQ changes will be written)..."
    $resp = Invoke-WebRequest -Uri $URL `
    -Headers @{ Authorization = "Bearer $TOKEN" } `
        -Method POST -UseBasicParsing
} else {
    Write-Host "Invoking live (soft-deletes WILL be written to BigQuery)..."
    $resp = Invoke-WebRequest -Uri $URL `
        -Headers @{ Authorization = "Bearer $TOKEN" } `
        -Method POST -UseBasicParsing
}

Write-Host "Response: $($resp.StatusCode)"
Write-Host $resp.Content
Pop-Location
