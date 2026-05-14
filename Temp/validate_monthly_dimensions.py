from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

query = """
SELECT
  month_start,
  Assigned_Group,
  CaseType,
  Fault_Cause,
  AIFaultCause,
  AIAtFault,
  AI_FaultDomain,
  counted_fault_tickets,
  total_counted_mttr_mins,
  ROUND(circuit_availability_pct, 6) AS circuit_availability_pct,
  ROUND(fault_rate_pct, 6) AS fault_rate_pct
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyMetrics`
WHERE month_start >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 2 MONTH)
ORDER BY month_start DESC, counted_fault_tickets DESC
LIMIT 20
"""

print("Sample rows with dimensions from CenterOps_MonthlyMetrics:")
for row in client.query(query).result():
    print(dict(row))
