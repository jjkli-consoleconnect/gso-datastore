from google.cloud import bigquery
from datetime import datetime
import os

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'G:/My Drive/Scripts/shared/service-account.json'
client = bigquery.Client()
today = datetime.utcnow().date()

query = f"""
SELECT Project, Status, COUNT(*) as cnt, SUM(RowCount) as rows 
FROM GSO.JiraTickets_progress 
WHERE DATE(LastRun) = '{today}' 
GROUP BY Project, Status 
ORDER BY Project, Status
"""

results = client.query(query).result()
print(f"{'Project':<40} {'Status':<12} {'Count':>6} {'Rows':>8}")
print('=' * 75)
for r in results:
    print(f"{r.Project:<40} {r.Status:<12} {r.cnt:>6} {int(r.rows or 0):>8}")
