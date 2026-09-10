"""Grant the UAT scheduled-query SA viewer access to the EDP source dataset."""
from google.cloud import bigquery

SOURCE = "edp-prod-lake-data-warehouse.DATA_676"
MEMBER = "serviceAccount:14417857267-compute@developer.gserviceaccount.com"
ROLE = "roles/bigquery.dataViewer"

client = bigquery.Client(project="pccw-internal-virt-agent-uat")
dataset = client.get_dataset(SOURCE)

entry = bigquery.AccessEntry(role=ROLE, entity_type="userByEmail", entity_id=MEMBER.split(":")[1])
if any(
    a.role == ROLE and a.entity_id == entry.entity_id and a.entity_type == "userByEmail"
    for a in dataset.access_entries
):
    print("Already granted, nothing to do.")
else:
    dataset.access_entries.append(entry)
    client.update_dataset(dataset, ["access_entries"])
    print(f"Granted {ROLE} on {SOURCE} to {MEMBER}")
