"""Verify AI enrichment columns on GSO.HDWL_AIInfused."""

from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")
query = """
SELECT
  column_name,
  data_type
FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'HDWL_AIInfused'
  AND column_name LIKE 'AI%'
ORDER BY ordinal_position
"""

for row in client.query(query).result():
    print(f"{row.column_name} | {row.data_type}")
