import requests, json
user='jjkli@consoleconnect.com'
with open('config.json') as f:
    token=json.load(f)['jira_api_token']
url='https://consoleconnect.atlassian.net/rest/api/2/project'
r=requests.get(url,auth=(user,token))
print('Status', r.status_code)
projects=r.json()
for p in projects:
    name=p.get('name'); key=p.get('key')
    if not name: continue
    if any(k in name for k in ['Knowledge','Consolidation','GS','GS&O']):
        print(f"{key} :: {name}")
print('Total projects', len(projects))
