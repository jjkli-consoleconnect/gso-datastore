from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

q = """
SELECT PromptVersion, COUNT(*) as cnt
FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
GROUP BY 1
ORDER BY 2 DESC
"""
print("=== PromptVersion breakdown ===")
for row in client.query(q).result():
    print(f"  {row.PromptVersion}  {row.cnt}")
