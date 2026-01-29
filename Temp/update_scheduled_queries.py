#!/usr/bin/env python3
"""Update all 24 CenterOps Hourly Snapshot scheduled queries with new SQL."""

from google.cloud.bigquery_datatransfer_v1 import DataTransferServiceClient
from google.protobuf import field_mask_pb2
import pathlib

# Load the SQL file
sql_file = pathlib.Path(r"g:\My Drive\Scripts\Temp\CenterOperationsShiftSnapshots_aggregated_scheduled.sql")
sql = sql_file.read_text(encoding='utf-8')

# Initialize the client
client = DataTransferServiceClient()

# Project details
project_id = "pccw-internal-virt-agent-uat"
location = "europe"

# List all transfer configs
parent = f"projects/{project_id}/locations/{location}"
configs = list(client.list_transfer_configs(parent=parent))

# Filter for CenterOps Hourly Snapshot queries
target_configs = [c for c in configs if c.display_name.startswith("CenterOps Hourly Snapshot")]

print(f"Found {len(target_configs)} CenterOps Hourly Snapshot queries to update\n")

success_count = 0
fail_count = 0

for config in sorted(target_configs, key=lambda x: x.display_name):
    print(f"Updating: {config.display_name} - ", end="", flush=True)
    
    try:
        # Update the transfer config with new SQL
        update_mask = field_mask_pb2.FieldMask(paths=["params"])
        
        config.params = {
            "query": sql,
            "destination_table_name_template": "CenterOperationsShiftSnapshotsAgg",
            "write_disposition": "WRITE_APPEND"
        }
        
        updated_config = client.update_transfer_config(
            transfer_config=config,
            update_mask=update_mask
        )
        
        print("SUCCESS")
        success_count += 1
        
    except Exception as e:
        print(f"FAILED - {str(e)}")
        fail_count += 1

print("\n" + "="*40)
print("Update Summary:")
print(f"  Total: {len(target_configs)}")
print(f"  Success: {success_count}")
print(f"  Failed: {fail_count}")
print("="*40)
