#!/bin/bash
set -e
# run from script dir so relative imports/files work
cd "$(dirname "$0")"
export GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json"
exec python main.py

