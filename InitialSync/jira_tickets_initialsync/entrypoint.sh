#!/bin/bash
set -e
# run from script dir so relative imports/files work
cd "$(dirname "$0")"
export GOOGLE_APPLICATION_CREDENTIALS="/app/shared/service-account.json"
echo "DEBUG: entrypoint running in $(pwd)"
echo "DEBUG: GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
if [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
	echo "DEBUG: credentials.json exists size=$(stat -c%s $GOOGLE_APPLICATION_CREDENTIALS)"
else
	echo "DEBUG: credentials.json does NOT exist"
fi
exec python main.py

