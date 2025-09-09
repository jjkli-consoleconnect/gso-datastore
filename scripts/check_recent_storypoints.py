from google.cloud import bigquery
import os

client = bigquery.Client()
project = client.project
print(f"Querying project: {project}")
query = '''
SELECT Key, Project, StoryPoints, Updated
FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`
WHERE Updated >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  AND StoryPoints IS NOT NULL
ORDER BY Updated DESC
LIMIT 20
'''

try:
    rows = client.query(query).result()
    found = False
    for r in rows:
        found = True
        print(f"{r.Key}\t{r.Project}\t{r.StoryPoints}\t{r.Updated}")
    if not found:
        print('No rows with StoryPoints found in the last 24 hours.')
except Exception as e:
    print('Query failed:', e)
    raise
