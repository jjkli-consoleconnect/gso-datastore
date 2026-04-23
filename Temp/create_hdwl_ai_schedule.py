"""
Creates (or updates) the HDWL_AIInfused scheduled query in BigQuery Data Transfer Service.
Schedule: daily at 19:00 UTC = 03:00 HKT
Location: EU
Project: pccw-internal-virt-agent-uat
"""

import os
import sys
from pathlib import Path

from google.cloud import bigquery_datatransfer_v1
from google.protobuf import struct_pb2

PROJECT_ID = "pccw-internal-virt-agent-uat"
LOCATION = "eu"
DATASET = "GSO"
DISPLAY_NAME = "HDWL AIInfused Daily Refresh"
# 19:00 UTC = 03:00 HKT (UTC+8)
SCHEDULE = "every day 19:00"

SQL_PATH = Path(__file__).parent.parent / "BigQuery" / "pccw-internal-virt-agent-uat" / "GSO" / "routines" / "HDWL_AIInfused.sql"


def get_existing_config(client, parent, display_name):
    for config in client.list_transfer_configs(parent=parent):
        if config.display_name == display_name:
            return config
    return None


def main():
    sql = SQL_PATH.read_text(encoding="utf-8")

    client = bigquery_datatransfer_v1.DataTransferServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"

    params = struct_pb2.Struct()
    params.fields["query"].string_value = sql

    existing = get_existing_config(client, parent, DISPLAY_NAME)

    if existing:
        print(f"Found existing config: {existing.name}")
        print("Updating...")
        existing.params.CopyFrom(params)
        existing.schedule = SCHEDULE
        update_mask = {"paths": ["params", "schedule"]}
        result = client.update_transfer_config(
            transfer_config=existing,
            update_mask=update_mask,
        )
        print(f"Updated: {result.name}")
    else:
        print("No existing config found. Creating new scheduled query...")
        transfer_config = bigquery_datatransfer_v1.TransferConfig(
            display_name=DISPLAY_NAME,
            data_source_id="scheduled_query",
            params=params,
            schedule=SCHEDULE,
            destination_dataset_id=DATASET,
        )
        result = client.create_transfer_config(
            parent=parent,
            transfer_config=transfer_config,
        )
        print(f"Created: {result.name}")
        print(f"Schedule: {result.schedule}  (19:00 UTC = 03:00 HKT)")

    print("Done.")


if __name__ == "__main__":
    main()
