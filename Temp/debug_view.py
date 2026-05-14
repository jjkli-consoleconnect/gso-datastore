from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

# Check view row count and distinct SRNo
query1 = """
SELECT 
  COUNT(*) AS total_rows,
  COUNT(DISTINCT SRNo) AS distinct_sr_numbers,
  COUNT(DISTINCT GSMP_Circuit_ID) AS distinct_circuits
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
"""

print("=== View Stats ===")
results = client.query(query1).result()
for row in results:
    print(f"Total rows: {row.total_rows}")
    print(f"Distinct SR numbers: {row.distinct_sr_numbers}")
    print(f"Distinct circuits: {row.distinct_circuits}")

# Check if join is working
query2 = """
SELECT 
  COUNT(*) AS hdwl_rows,
  COUNT(DISTINCT GSMP_Circuit_ID) AS hdwl_circuits
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
"""

print("\n=== HDWL Stats (last 2 years) ===")
results = client.query(query2).result()
for row in results:
    print(f"HDWL rows: {row.hdwl_rows}")
    print(f"HDWL circuits: {row.hdwl_circuits}")

# Check SHRPeople with Operation status
query3 = """
SELECT 
  COUNT(*) AS total_rows,
  COUNT(DISTINCT SRNo) AS distinct_sr_numbers,
  COUNT(DISTINCT Insight_Circuit_ID) AS distinct_circuits
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
WHERE SR_Status = 'Operation'
"""

print("\n=== SHRPeople (Operation status) ===")
results = client.query(query3).result()
for row in results:
    print(f"Total rows: {row.total_rows}")
    print(f"Distinct SR numbers: {row.distinct_sr_numbers}")
    print(f"Distinct circuits: {row.distinct_circuits}")

# Check if GSMP_Circuit_ID exists in HDWL
query4 = """
SELECT 
  COUNT(*) AS rows_with_gsmp,
  COUNT(DISTINCT GSMP_Circuit_ID) AS distinct_gsmp
FROM `pccw-internal-virt-agent-uat.GSO.HDWL`
WHERE GSMP_Circuit_ID IS NOT NULL
  AND Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
"""

print("\n=== HDWL GSMP_Circuit_ID ===")
results = client.query(query4).result()
for row in results:
    print(f"Rows with GSMP_Circuit_ID: {row.rows_with_gsmp}")
    print(f"Distinct GSMP_Circuit_ID: {row.distinct_gsmp}")
