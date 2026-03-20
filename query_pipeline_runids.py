from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
run_ids = [
    '7ed1894c-4a6d-45dc-a845-540f52ee1cae',
    '9883ebc9-5a15-4fdc-a4a2-c5cede327af9',
    'ba532f9a-5aea-4255-a570-9ac47ea268c9',
]

for run_id in run_ids:
    print(f'===== {run_id} =====')
    query = f'''
    SELECT PipelineName, RunId, Status, Message, RunTime, DurationSeconds, WindowStart, WindowEnd, RowsMerged
    FROM `GSO.PipelineRuns`
    WHERE RunId = '{run_id}'
    ORDER BY RunTime ASC
    '''
    for row in client.query(query).result():
        print(dict(row))
    print()
