@echo off
REM Batch file to run the hourly sync script hidden
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "G:\My Drive\Scripts\Hourly\RegularSync\run_hourly_all.ps1"