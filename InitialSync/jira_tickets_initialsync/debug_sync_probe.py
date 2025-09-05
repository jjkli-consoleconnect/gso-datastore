from __future__ import print_function
import main, os
from datetime import datetime, timezone, timedelta

# Monkeypatch BigQuery helpers to avoid real BigQuery API calls
main.table_exists = lambda client,dataset,table: True
main.create_or_replace_table = lambda client,dataset,table,schema: True
main.wait_for_table = lambda client,dataset,table,retries=10,delay=2: True
main.ensure_table_columns = lambda client,dataset,table,schema: True
main.insert_rows_with_retry = lambda client,dataset,table,rows,schema,retries=6,delay=6: True
main.delete_table_quiet = lambda client,dataset,table: None

cfg=main.load_config()
user=os.environ.get('JIRA_USERNAME') or cfg.get('jira_username')
token=os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
auth=(user,token)
now=datetime.now(timezone.utc)
ws=now - timedelta(minutes=30)
we=now - timedelta(minutes=20)
proj='GS&O Data Analytics'
# shared filter logic removed; force per-project JQL for probe
filter_jql=None
jql=f'(project = "{proj}") AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\"'
print('Testing sync_tickets_window with jql:', jql)
# Use a fake client placeholder since we've monkeypatched BQ helpers
fake_client = object()
res = main.sync_tickets_window(jql, auth, fake_client, 'GSO', 'JiraTickets', ws, we)
print('sync_tickets_window returned:', res)
