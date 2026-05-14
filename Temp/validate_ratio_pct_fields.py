from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

q1 = """
SELECT
  month_start,
  up_pct,
  down_pct,
  fault_rate_pct,
  (up_pct + down_pct) AS sum_up_down
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyUpDown`
WHERE Assigned_Group = 'ALL'
ORDER BY month_start DESC
LIMIT 5
"""

q2 = """
SELECT
  month_start,
  circuit_availability_pct,
  fault_rate_pct
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyMetrics`
ORDER BY month_start DESC
LIMIT 5
"""

print('CenterOps_MonthlyUpDown (should be 0-1 ratios):')
for row in client.query(q1).result():
    print(dict(row))

print('\nCenterOps_MonthlyMetrics (should be 0-1 ratios):')
for row in client.query(q2).result():
    print(dict(row))
