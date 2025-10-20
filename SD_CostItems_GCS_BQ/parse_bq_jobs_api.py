from google.cloud import bigquery
from google.oauth2 import service_account
import json
import os

KEY_PATH = r"g:\My Drive\Scripts\jira-bigquery-key.json"
PROJECT = 'pccw-internal-virt-agent-uat'

creds = service_account.Credentials.from_service_account_file(KEY_PATH)
client = bigquery.Client(credentials=creds, project=PROJECT)

print('Listing recent jobs (max 200) for project', PROJECT)
for job in client.list_jobs(max_results=200):
    try:
        j = job.to_api_repr()
    except Exception:
        continue
    job_id = j.get('id')
    typ = j.get('configuration', {}).get('jobType')
    state = j.get('status', {}).get('state')
    err = j.get('status', {}).get('errorResult')
    # Heuristic: print loads, errors, or jobs referencing our temp table prefix
    if typ == 'LOAD' or err or 'temp_sd_costitems' in json.dumps(j):
        print('\nJOB_ID:', job_id)
        print('TYPE:', typ)
        print('STATE:', state)
        print('ERROR_RESULT:', err)
        if j.get('status', {}).get('errors'):
            print('ERRORS:')
            for e in j['status']['errors']:
                print(' -', json.dumps(e))
        print('CONFIG_SNIPPET:', json.dumps(j.get('configuration', {}))[:1000])
print('\nDone')
