from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

query = """
SELECT
  COUNT(*) AS rows_total,
  COUNTIF(Is_Counted_Fault) AS counted_fault_rows,
  SUM(COALESCE(TrueMTTR_mins, 0)) AS total_mttr_mins,
  SUM(COALESCE(Counted_MTTR_mins, 0)) AS counted_mttr_mins
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
WHERE Closed_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
"""

row = list(client.query(query).result())[0]
print("Last 30 days summary:")
print(f"Rows total: {row.rows_total}")
print(f"Counted fault rows: {row.counted_fault_rows}")
print(f"Total MTTR mins: {row.total_mttr_mins}")
print(f"Counted MTTR mins: {row.counted_mttr_mins}")
