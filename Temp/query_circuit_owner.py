from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
query = """
SELECT DISTINCT Circuit_Owner 
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople` 
WHERE Circuit_Owner IS NOT NULL 
ORDER BY Circuit_Owner
LIMIT 20
"""
results = client.query(query).result()
print("Circuit_Owner values from SHRPeople:\n")
for row in results:
    print(f"  - {row.Circuit_Owner}")
