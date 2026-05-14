from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

query = """
SELECT
  month_year,
  Assigned_Group,
  Fault_Cause,
  number_of_circuits,
  counted_fault_tickets,
  total_counted_mttr_mins,
  ROUND(up_pct, 6) AS up_pct,
  ROUND(down_pct, 6) AS down_pct,
  ROUND(fault_rate_pct, 6) AS fault_rate_pct
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyUpDown`
WHERE month_start >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 3 MONTH)
  AND Assigned_Group = 'ALL'
ORDER BY month_start DESC
LIMIT 12
"""

print("Sample monthly overall rows (Assigned_Group=ALL):")
for row in client.query(query).result():
    print(dict(row))
