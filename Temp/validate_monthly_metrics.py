from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

query = """
SELECT
  month_start,
  number_of_circuits,
  month_minutes,
  counted_fault_tickets,
  total_counted_mttr_mins,
  ROUND(circuit_availability * 100, 6) AS circuit_availability_pct,
  ROUND(fault_rate * 100, 6) AS fault_rate_pct
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyMetrics`
ORDER BY month_start DESC
LIMIT 6
"""

print("Recent monthly metrics:")
for row in client.query(query).result():
    print(dict(row))
