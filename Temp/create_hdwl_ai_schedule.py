"""Deploy/update the HDWL AIInfused scheduled query in BigQuery DTS."""
from google.cloud import bigquery_datatransfer_v1
import pathlib

SQL_PATH = (
    pathlib.Path(__file__).parent.parent
    / "BigQuery"
    / "pccw-internal-virt-agent-uat"
    / "GSO"
    / "routines"
    / "HDWL_AIInfused.sql"
)
QUERY_SQL = SQL_PATH.read_text(encoding="utf-8")

PROJECT_ID = "pccw-internal-virt-agent-uat"
LOCATION = "EU"
DATASET_ID = "GSO"
DISPLAY_NAME = "HDWL AIInfused Daily Refresh"
SCHEDULE = "every day 19:00"

client = bigquery_datatransfer_v1.DataTransferServiceClient()
parent = f"projects/{PROJECT_ID}/locations/{LOCATION.lower()}"

existing = None
for config in client.list_transfer_configs(parent=parent):
    if config.display_name == DISPLAY_NAME:
        existing = config
        break

transfer_config = bigquery_datatransfer_v1.TransferConfig(
    display_name=DISPLAY_NAME,
    data_source_id="scheduled_query",
    destination_dataset_id=DATASET_ID,
    schedule=SCHEDULE,
    params={"query": QUERY_SQL},
)

if existing:
    print(f"Found existing config: {existing.name}")
    transfer_config.name = existing.name
    updated = client.update_transfer_config(
        transfer_config=transfer_config,
        update_mask={"paths": ["params", "schedule", "display_name"]},
    )
    print(f"Updating...")
    print(f"Updated: {updated.name}")
else:
    created = client.create_transfer_config(
        parent=parent,
        transfer_config=transfer_config,
    )
    print(f"Created: {created.name}")

print("Done.")
