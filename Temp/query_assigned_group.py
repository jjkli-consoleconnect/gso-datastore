from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
query = """
SELECT DISTINCT Assigned_Group 
FROM `pccw-internal-virt-agent-uat.GSO.HDWL` 
WHERE Assigned_Group IS NOT NULL 
ORDER BY Assigned_Group
LIMIT 20
"""
results = client.query(query).result()
print("Assigned_Group values from HDWL:\n")
for row in results:
    print(f"  - {row.Assigned_Group}")
