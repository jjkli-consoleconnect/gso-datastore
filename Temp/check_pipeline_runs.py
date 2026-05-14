from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

q = """
SELECT
  RunID,
  Status,
  RunTime,
  DurationSeconds,
  RowsMerged,
  LogLevel,
  ErrorCode,
  Message
FROM `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
WHERE PipelineName = 'pubsub - SHRPeople'
ORDER BY RunTime DESC
LIMIT 40
"""

rows = list(client.query(q).result())
print(f"{'RunID':<36} {'Status':<14} {'RunTime':<32} {'Dur(s)':<8} {'Rows':<6} Message")
print("-" * 130)
for r in rows:
    print(f"{str(r['RunID']):<36} {str(r['Status']):<14} {str(r['RunTime']):<32} {str(r['DurationSeconds']):<8} {str(r['RowsMerged']):<6} {str(r['Message'])[:50]}")

stale = [r for r in rows if r['Status'] == 'RUNNING']
print(f"\nSTALE RUNNING count: {len(stale)}")
for r in stale:
    print(f"  RunID={r['RunID']}  RunTime={r['RunTime']}")

