from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

query = """
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(ABS((up_pct + down_pct) - 100) > 0.000001) AS rows_not_100,
  MIN(up_pct + down_pct) AS min_sum,
  MAX(up_pct + down_pct) AS max_sum,
  AVG(up_pct + down_pct) AS avg_sum
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyUpDown`
"""

query2 = """
SELECT
  month_year,
  Assigned_Group,
  Fault_Cause,
  up_pct,
  down_pct,
  (up_pct + down_pct) AS sum_pct,
  ABS((up_pct + down_pct) - 100) AS diff
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyUpDown`
WHERE ABS((up_pct + down_pct) - 100) > 0.000001
ORDER BY diff DESC
LIMIT 20
"""

print("Overall sum check:")
for r in client.query(query).result():
    print(dict(r))

print("\nRows where up+down != 100:")
for r in client.query(query2).result():
    print(dict(r))
