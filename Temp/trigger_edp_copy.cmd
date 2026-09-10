@echo off
rem Trigger a manual run of the EDP-SR EU copy transfer
for /f "usebackq delims=" %%i in (`gcloud auth print-access-token`) do set TOKEN=%%i
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffK')"') do set NOW=%%i

curl -s -X POST "https://bigquerydatatransfer.googleapis.com/v1/projects/14417857267/locations/europe/transferConfigs/6ab3293a-0000-2cfc-a8ef-582429ae6af8:run" ^
  -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
  -d "{\"requestedRunTime\":\"%NOW%\"}"
