import requests, json
user='jjkli@consoleconnect.com'
with open('config.json') as f: token=json.load(f)['jira_api_token']
for url in ['https://consoleconnect.atlassian.net/rest/api/3/project/search','https://consoleconnect.atlassian.net/rest/api/3/project']:
    r=requests.get(url,auth=(user,token))
    print('URL', url, 'status', r.status_code)
    print(r.text[:400])
