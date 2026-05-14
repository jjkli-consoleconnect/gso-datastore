from google.cloud import bigquery

client = bigquery.Client(project='pccw-internal-virt-agent-uat')

# Get schema
table = client.get_table('pccw-internal-virt-agent-uat.GSO.HDWL')
print("HDWL table fields:\n")
for field in table.schema:
    print(f"  - {field.name} ({field.field_type})")

# Look for group/owner related fields
print("\n\nFields containing 'group', 'owner', 'assign', or 'team':\n")
for field in table.schema:
    field_name_lower = field.name.lower()
    if any(term in field_name_lower for term in ['group', 'owner', 'assign', 'team', 'support']):
        print(f"  - {field.name}")
