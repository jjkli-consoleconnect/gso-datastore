import os, json, requests, urllib.parse, sys

def load_config():
    candidates=[]
    script_dir=os.path.dirname(__file__)
    repo_root=os.path.normpath(os.path.join(script_dir, '..'))
    candidates.append(os.path.join(script_dir, 'jira_tickets_initialsync', 'config.json'))
    candidates.append(os.path.join(repo_root, 'config.json'))
    candidates.append(os.path.join(repo_root, 'Hourly', 'jira_tickets', 'config.json'))
    env_cfg=os.environ.get('JIRA_CONFIG_JSON')
    if env_cfg:
        try:
            return json.loads(env_cfg)
        except Exception:
            pass
    for p in candidates:
        try:
            if p and os.path.exists(p):
                with open(p,'r',encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
    return None

cfg=load_config()
username=os.environ.get('JIRA_USERNAME') or (cfg and cfg.get('jira_username'))
token=os.environ.get('JIRA_API_TOKEN') or (cfg and cfg.get('jira_api_token'))
base='https://consoleconnect.atlassian.net'
if not username or not token:
    print('Missing credentials: set JIRA_USERNAME and JIRA_API_TOKEN or a config.json with jira_username/jira_api_token')
    sys.exit(2)

auth=(username, token)

# sample jql or use filter id
sample_jql='project = "GS&O Data Analytics"'
filter_id='19979'

endpoints=[
    ('GET latest search jql', f'{base}/rest/api/latest/search?jql={urllib.parse.quote(sample_jql)}', 'GET', None),
    ('GET latest search filter', f'{base}/rest/api/latest/search?filter={filter_id}', 'GET', None),
    ('GET api3 search jql', f'{base}/rest/api/3/search?jql={urllib.parse.quote(sample_jql)}', 'GET', None),
    ('GET api3 search filter', f'{base}/rest/api/3/search?filter={filter_id}', 'GET', None),
    ('GET api3 search/jql', f'{base}/rest/api/3/search/jql?jql={urllib.parse.quote(sample_jql)}', 'GET', None),
    ('GET filter endpoint', f'{base}/rest/api/3/filter/{filter_id}', 'GET', None),
    ('POST api3 search JSON jql', f'{base}/rest/api/3/search', 'POST', {'jql': sample_jql, 'startAt':0, 'maxResults':1}),
    ('POST api3 search/jql JSON', f'{base}/rest/api/3/search/jql', 'POST', {'jql': sample_jql, 'startAt':0, 'maxResults':1}),
    ('POST latest search JSON', f'{base}/rest/api/latest/search', 'POST', {'jql': sample_jql, 'startAt':0, 'maxResults':1}),
]

headers={'Accept':'application/json','Content-Type':'application/json'}

print('Probing Jira API endpoints using user:', username)
for name, url, method, body in endpoints:
    try:
        print('\n--', name, url)
        if method=='GET':
            r = requests.get(url, auth=auth, headers={'Accept':'application/json'}, timeout=20)
        else:
            r = requests.post(url, auth=auth, headers=headers, json=body, timeout=20)
        print('Status:', r.status_code)
        snippet = (r.text or '')[:1000]
        print('Response snippet:', snippet)
        if r.status_code==200:
            print('\nSuccess with:', name)
            break
    except Exception as e:
        print('Exception:', e)

print('\nProbe finished')
