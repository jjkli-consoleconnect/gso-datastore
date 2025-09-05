from __future__ import print_function
import main
import os
from datetime import datetime,timezone,timedelta

cfg=main.load_config()
user=os.environ.get('JIRA_USERNAME') or cfg.get('jira_username')
token=os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
auth=(user,token)
# shared filter logic removed; force per-project JQL for probe
filter_jql=None
print('filter_jql:', filter_jql)
# Build a test window similar to main
now=datetime.now(timezone.utc)
ws=now - timedelta(minutes=30)
we=now - timedelta(minutes=20)
print('ws,we',ws,we)
if filter_jql:
    jql=f"({filter_jql}) AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
else:
    proj='GS&O Data Analytics'
    jql=f'(project = "{proj}") AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\"'
print('Executing test JQL:', jql)
res=main.fetch_issues_page(auth,jql,0,5)
print('fetch result type:', type(res))
if res is None:
    print('fetch returned None')
else:
    print('keys:', list(res.keys()))
    print('total:', res.get('total'))
    print('issues len:', len(res.get('issues',[])))
    for issue in res.get('issues',[]):
        print('issue key', issue.get('key'))
