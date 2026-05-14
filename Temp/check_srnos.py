from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

# Check SRNo distribution
query = """
SELECT 
  SRNo,
  COUNT(*) AS ticket_count,
  COUNT(DISTINCT GSMP_Circuit_ID) AS distinct_circuits
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
GROUP BY SRNo
ORDER BY ticket_count DESC
LIMIT 50
"""

print("=== SRNo Distribution in View ===")
results = client.query(query).result()
for row in results:
    print(f"SRNo: {row.SRNo:30} | Tickets: {row.ticket_count:8} | Circuits: {row.distinct_circuits:6}")

# Check NULL SRNo
query2 = """
SELECT 
  COUNT(*) AS rows_with_null_srno
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
WHERE SRNo IS NULL
"""

print("\n=== NULL SRNo ===")
results = client.query(query2).result()
for row in results:
    print(f"Rows with NULL SRNo: {row.rows_with_null_srno}")
