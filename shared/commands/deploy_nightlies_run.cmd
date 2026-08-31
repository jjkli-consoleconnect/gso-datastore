@echo off
setlocal
set "OUTPUT_FILE=%TEMP%\scripts-nightly-deploy.log"
call "%~dp0deploy_nightlies.cmd" > "%OUTPUT_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo Deployment log: %OUTPUT_FILE%
exit /b %EXIT_CODE%