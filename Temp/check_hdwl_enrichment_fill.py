"""Check whether new enrichment fields are populated."""

from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")
query = """
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(AI_FaultDomain IS NOT NULL) AS filled_fault_domain,
  COUNTIF(AI_ConfidenceScore IS NOT NULL) AS filled_confidence,
  MAX(ClassifiedAt) AS latest_classified
FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
"""

row = list(client.query(query).result())[0]
print(f"total_rows={row.total_rows}")
print(f"filled_fault_domain={row.filled_fault_domain}")
print(f"filled_confidence={row.filled_confidence}")
print(f"latest_classified={row.latest_classified}")
