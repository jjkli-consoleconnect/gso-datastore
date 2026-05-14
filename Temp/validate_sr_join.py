from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

query = """
SELECT
  COUNT(*) AS total_rows,
  COUNT(DISTINCT SRNo) AS distinct_shr_srno,
  COUNT(DISTINCT SRno) AS distinct_hdwl_srno,
  COUNTIF(Incident_Number IS NOT NULL) AS rows_with_ticket,
  COUNT(DISTINCT IF(Incident_Number IS NOT NULL, SRNo, NULL)) AS srno_with_ticket
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
"""

rows = list(client.query(query).result())
r = rows[0]
print('View stats after SRNo join:')
print(f"Total rows: {r.total_rows}")
print(f"Distinct SHR SRNo: {r.distinct_shr_srno}")
print(f"Distinct HDWL SRno (matched): {r.distinct_hdwl_srno}")
print(f"Rows with ticket: {r.rows_with_ticket}")
print(f"SRs with at least one ticket: {r.srno_with_ticket}")

query2 = """
SELECT SRNo, COUNT(*) AS cnt
FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
WHERE Incident_Number IS NOT NULL
GROUP BY SRNo
ORDER BY cnt DESC
LIMIT 10
"""

print('\nTop matched SRs:')
for row in client.query(query2).result():
    print(f"{row.SRNo}: {row.cnt}")
