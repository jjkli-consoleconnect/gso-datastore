@echo off
setlocal

for %%I in ("%~dp0..\..") do set "REPO_ROOT=%%~fI"
where gcloud.cmd >nul 2>&1
if errorlevel 1 (
    echo gcloud.cmd was not found on PATH.
    exit /b 1
)

set COMMON=--gen2 --runtime python311 --region europe-west2 --source . --entry-point main --trigger-http --timeout 3600s --memory 2048Mi --max-instances 5 --vpc-connector projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn --egress-settings all --service-account jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com --no-allow-unauthenticated --project pccw-internal-virtual-agent

pushd "%REPO_ROOT%\CloudFunctions\JiraTicketsNightly"
echo === TICKETS NIGHTLY ===
call gcloud.cmd functions deploy jira-tickets-nightly %COMMON%
if errorlevel 1 goto :err

popd
pushd "%REPO_ROOT%\CloudFunctions\JiraCommentsNightly"
echo === COMMENTS NIGHTLY ===
call gcloud.cmd functions deploy jira-comments-nightly %COMMON%
if errorlevel 1 goto :err

popd
pushd "%REPO_ROOT%\CloudFunctions\JiraChangelogsNightly"
echo === CHANGELOGS NIGHTLY ===
call gcloud.cmd functions deploy jira-changelogs-nightly %COMMON%
if errorlevel 1 goto :err

popd
echo ALL_DEPLOYS_OK
exit /b 0

:err
set "EXIT_CODE=%ERRORLEVEL%"
popd
echo DEPLOY_FAILED
exit /b %EXIT_CODE%