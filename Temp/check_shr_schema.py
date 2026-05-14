from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')
table = client.get_table('pccw-internal-virt-agent-uat.GSO.SHRPeople')
print("SHRPeople table fields:\n")
for field in table.schema:
    print(f"  - {field.name}")
