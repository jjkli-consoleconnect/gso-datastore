#!/bin/bash
set -e
# Ensure we run from the script's directory so `python main.py` finds the local main.py
cd "$(dirname "$0")"
export GOOGLE_APPLICATION_CREDENTIALS="/app/shared/service-account.json"
export PYTHONPATH="/app:$PYTHONPATH"
exec python main.py

