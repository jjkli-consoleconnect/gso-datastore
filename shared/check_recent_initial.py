from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

# Check the most recent initial sync run
query = """
SELECT 
    PipelineName,
    WindowStart,
    WindowEnd,
    RowsMerged,
    Status,
    RunTime,
    Message
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE PipelineName = 'jira_tickets_initialsync'
ORDER BY RunTime DESC 
LIMIT 5
"""

results = list(client.query(query).result())

print("Most recent initial sync runs:")
print(f"{'PipelineName':<30} | {'RowsMerged':<12} | {'Status':<10} | {'RunTime':<30}")
print("-" * 100)

for r in results:
    rows_merged = r.RowsMerged if r.RowsMerged is not None else 0
    window_start = str(r.WindowStart) if r.WindowStart else "NULL"
    window_end = str(r.WindowEnd) if r.WindowEnd else "NULL"
    run_time = str(r.RunTime) if r.RunTime else "NULL"
    status = r.Status if r.Status else "NULL"
    message = r.Message[:50] + "..." if r.Message and len(r.Message) > 50 else r.Message or ""
    
    print(f"{r.PipelineName:<30} | {rows_merged:<12} | {status:<10} | {run_time:<30}")
    if message:
        print(f"  Message: {message}")
    print()