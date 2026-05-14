from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

query = """
SELECT
  snapshot_month,
  SR_Status,
  Circuit_Owner,
  sr_count
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople_StatusMonthlyCounts`
ORDER BY snapshot_month DESC, sr_count DESC
LIMIT 30
"""

print("Sample snapshot rows:")
for row in client.query(query).result():
    print(dict(row))

query2 = """
SELECT
  snapshot_month,
  SUM(sr_count) AS total_sr
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople_StatusMonthlyCounts`
GROUP BY snapshot_month
ORDER BY snapshot_month DESC
LIMIT 12
"""

print("\nMonthly total SR counts:")
for row in client.query(query2).result():
    print(dict(row))
