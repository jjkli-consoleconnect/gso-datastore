from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
query = '''
SELECT
  PipelineName,
  RunId,
  Status,
  Message,
  RunTime,
  DurationSeconds,
  WindowStart,
  WindowEnd,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), RunTime, MINUTE) AS minutes_running
FROM `GSO.PipelineRuns`
WHERE PipelineName IN (
  'GCP - JiraChangelogsNightly',
  'GCP - JiraCommentsNightly',
  'GCP - JiraTicketsNightly'
)
  AND Status = 'RUNNING'
ORDER BY RunTime DESC
LIMIT 50
'''

rows = list(client.query(query).result())
print(f'RUNNING rows: {len(rows)}')
for row in rows:
    print('---')
    print(f"PipelineName: {row['PipelineName']}")
    print(f"RunId: {row['RunId']}")
    print(f"RunTime: {row['RunTime']}")
    print(f"MinutesRunning: {row['minutes_running']}")
    print(f"Message: {row['Message']}")
    print(f"DurationSeconds: {row['DurationSeconds']}")
    print(f"WindowStart: {row['WindowStart']}")
    print(f"WindowEnd: {row['WindowEnd']}")
