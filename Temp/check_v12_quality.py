from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

q = """
SELECT AI_FaultDomain, COUNT(*) as cnt,
  ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER(), 1) AS pct
FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
WHERE PromptVersion = 'hdwl-firstresponse-v12-enriched'
GROUP BY 1 ORDER BY 2 DESC
"""
print("=== AI_FaultDomain distribution (v12) ===")
for row in client.query(q).result():
    label = row.AI_FaultDomain or "NULL"
    print(f"  {label:<25} {row.cnt:>6}  ({row.pct}%)")

q2 = """
SELECT
  COUNTIF(AI_FaultDomain = 'Unknown') AS unknown_domain,
  COUNTIF(AI_SuspectedParty IS NULL) AS null_suspected_party,
  COUNTIF(AI_PrimarySymptom IS NULL) AS null_primary_symptom,
  COUNTIF(AI_LikelyRootCause IS NULL) AS null_root_cause,
  COUNTIF(AI_DeviceInterfaceContext IS NULL) AS null_device_ctx,
  COUNT(*) AS total
FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
WHERE PromptVersion = 'hdwl-firstresponse-v12-enriched'
"""
print("\n=== Null/Unknown counts (v12) ===")
for row in client.query(q2).result():
    total = row.total
    print(f"  unknown_domain       {row.unknown_domain:>6}  ({round(row.unknown_domain*100/total,1)}%)")
    print(f"  null_suspected_party {row.null_suspected_party:>6}  ({round(row.null_suspected_party*100/total,1)}%)")
    print(f"  null_primary_symptom {row.null_primary_symptom:>6}  ({round(row.null_primary_symptom*100/total,1)}%)")
    print(f"  null_root_cause      {row.null_root_cause:>6}  ({round(row.null_root_cause*100/total,1)}%)")
    print(f"  null_device_ctx      {row.null_device_ctx:>6}  ({round(row.null_device_ctx*100/total,1)}%)")
    print(f"  total                {total:>6}")
