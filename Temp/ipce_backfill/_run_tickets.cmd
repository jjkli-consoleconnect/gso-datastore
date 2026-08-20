@echo off
cd /d "g:\My Drive\Scripts\Temp\ipce_backfill"
python backfill_tickets.py > tickets_run.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> tickets_run.log

