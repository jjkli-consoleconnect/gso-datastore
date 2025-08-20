#!/bin/bash
export GOOGLE_APPLICATION_CREDENTIALS="/app/credentials.json"

# Prefer mounted JQL file if present
if [ -f "/config/JQL.txt" ]; then
	export JQL_FILE="/config/JQL.txt"
elif [ -f "/data/JQL.txt" ]; then
	export JQL_FILE="/data/JQL.txt"
fi

python main.py
