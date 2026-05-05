"""Amend the existing MSS AIInfused scheduled query in BigQuery DTS and apply seeds labels."""
from google.cloud import bigquery_datatransfer_v1
import google.auth
import google.auth.transport.requests
import requests
import pathlib

SQL_PATH = (
    pathlib.Path(__file__).parent.parent
    / "BigQuery"
    / "pccw-internal-virt-agent-uat"
    / "GSO"
    / "routines"
    / "MSS_AIInfused.sql"
)
QUERY_SQL = SQL_PATH.read_text(encoding="utf-8")

# The existing scheduled query to amend
EXISTING_CONFIG_NAME = "projects/14417857267/locations/europe/transferConfigs/6a1ea328-0000-26a9-95c8-001a114d3040"

DATASET_ID = "GSO"
DISPLAY_NAME = "MSS AIInfused Daily Refresh"
SCHEDULE = "every day 19:00"
LABELS = {
    "seeds_environment": "prod",
    "seeds_product": "mss_aiinfused",
    "seeds_component": "bigquery",
}

client = bigquery_datatransfer_v1.DataTransferServiceClient()

# Step 1: Update SQL, schedule, display_name via client library
transfer_config = bigquery_datatransfer_v1.TransferConfig(
    name=EXISTING_CONFIG_NAME,
    display_name=DISPLAY_NAME,
    destination_dataset_id=DATASET_ID,
    schedule=SCHEDULE,
    params={"query": QUERY_SQL},
)
updated = client.update_transfer_config(
    transfer_config=transfer_config,
    update_mask={"paths": ["params", "schedule", "display_name"]},
)
print(f"Updated config: {updated.name}")

# Step 2: PATCH labels via REST API (not exposed in proto client)
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
url = f"https://bigquerydatatransfer.googleapis.com/v1/{EXISTING_CONFIG_NAME}"
resp = requests.patch(
    url,
    params={"updateMask": "labels"},
    headers={"Authorization": f"Bearer {creds.token}"},
    json={"labels": LABELS},
)
if not resp.ok:
    print(f"Labels PATCH f