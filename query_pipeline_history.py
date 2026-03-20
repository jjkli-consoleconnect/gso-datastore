from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
query = '''
WITH ranked AS (
  SELECT
    PipelineName,
    RunId,
    Status,
    Message,
    RunTime,
    DurationSeconds,
    WindowStart,
    WindowEnd,
    ROW_NUMBER() OVER (PARTITION BY PipelineName ORDER BY RunTime DESC) AS rn
  FROM `GSO.PipelineRuns`
  WHERE PipelineName IN (
    'GCP - JiraChangelogsNightly',
    'GCP - JiraCommentsNightly',
    'GCP - JiraTicketsNightly'
  )
)
SELECT *
FROM ranked
WHERE rn <= 8
ORDER BY PipelineName, RunTime DESC
'''
for row in client.query(query).result():
    print(dict(row))
