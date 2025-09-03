import os, requests, json

user = os.environ.get('JIRA_USERNAME')
token = os.environ.get('JIRA_API_TOKEN')
if not user or not token:
    print('MISSING_CREDS')
    raise SystemExit(1)

auth = (user, token)
base = 'https://consoleconnect.atlassian.net'
issue_key = 'CSM-1500'
# 1) issue updated
try:
    r = requests.get(f'{base}/rest/api/2/issue/{issue_key}?fields=updated', auth=auth, timeout=30)
    print('ISSUE_STATUS', r.status_code)
    if r.status_code==200:
        j=r.json(); print('ISSUE_UPDATED', j.get('fields',{}).get('updated'))
    else:
        print('ISSUE_BODY', (r.text or '')[:400])
except Exception as e:
    print('ISSUE_ERROR', e)

# 2) search JQL window
payload = {'jql':'project = "Customer Success Management" AND updated >= "2025/08/14 16:00" AND updated < "2025/08/16 16:00"', 'startAt':0, 'maxResults':50, 'fields':['key','updated']}
try:
    r = requests.post(f'{base}/rest/api/2/search', json=payload, auth=auth, timeout=60)
    print('SEARCH_STATUS', r.status_code)
    if r.status_code==200:
        j=r.json()
        print('SEARCH_TOTAL', j.get('total'))
        keys = [iss.get('key') for iss in j.get('issues',[])]
        print('IN_SEARCH', 'CSM-1500' in keys)
        if len(keys)>0:
            print('SEARCH_KEYS', ','.join(keys[:50]))
    else:
        print('SEARCH_BODY', (r.text or '')[:400])
except Exception as e:
    print('SEARCH_ERROR', e)

# 3) comments list
try:
    r = requests.get(f'{base}/rest/api/2/issue/{issue_key}/comment', auth=auth, timeout=60)
    print('COMMENTS_STATUS', r.status_code)
    if r.status_code==200:
        j=r.json(); print('COMMENTS_TOTAL', j.get('total'))
        for c in j.get('comments',[]):
            print('COMMENT', c.get('id'), 'created='+c.get('created'), 'updated='+c.get('updated'))
    else:
        print('COMMENTS_BODY', (r.text or '')[:400])
except Exception as e:
    print('COMMENTS_ERROR', e)
