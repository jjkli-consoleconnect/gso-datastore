import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from google.cloud import bigquery_datatransfer_v1
from google.protobuf import field_mask_pb2, struct_pb2
from google.oauth2.credentials import Credentials

SQL_PATH = Path(r"g:\My Drive\Scripts\Temp\CenterOperationsShiftSnapshots_aggregated_scheduled.sql")
DEST_TABLE_TEMPLATE = "CenterOperationsShiftSnapshotsAgg"
WRITE_DISPOSITION = "WRITE_APPEND"

# All 24 CenterOps scheduled queries (00 already patched manually)
CONFIGS = [
    {"display_name": "CenterOps Hourly Snapshot 00", "schedule": "every day 00:00", "name": "projects/14417857267/locations/europe/transferConfigs/698a7062-0000-2ac9-a68d-3c286d48384e"},
    {"display_name": "CenterOps Hourly Snapshot 01", "schedule": "every day 01:00", "name": "projects/14417857267/locations/europe/transferConfigs/69735499-0000-214a-940b-582429bd4190"},
    {"display_name": "CenterOps Hourly Snapshot 02", "schedule": "every day 02:00", "name": "projects/14417857267/locations/europe/transferConfigs/69730a2a-0000-2266-9830-582429bd07b8"},
    {"display_name": "CenterOps Hourly Snapshot 03", "schedule": "every day 03:00", "name": "projects/14417857267/locations/europe/transferConfigs/6971f546-0000-2634-8d93-3c286d48a702"},
    {"display_name": "CenterOps Hourly Snapshot 04", "schedule": "every day 04:00", "name": "projects/14417857267/locations/europe/transferConfigs/6978e9c1-0000-29ea-8488-d4f547fe80dc"},
    {"display_name": "CenterOps Hourly Snapshot 05", "schedule": "every day 05:00", "name": "projects/14417857267/locations/europe/transferConfigs/69730355-0000-2ddd-bc21-582429bd08fc"},
    {"display_name": "CenterOps Hourly Snapshot 06", "schedule": "every day 06:00", "name": "projects/14417857267/locations/europe/transferConfigs/69975d87-0000-2909-b4ee-582429bd6c60"},
    {"display_name": "CenterOps Hourly Snapshot 07", "schedule": "every day 07:00", "name": "projects/14417857267/locations/europe/transferConfigs/696c2ff4-0000-28c7-85d2-fc41166c49b9"},
    {"display_name": "CenterOps Hourly Snapshot 08", "schedule": "every day 08:00", "name": "projects/14417857267/locations/europe/transferConfigs/6999156a-0000-2644-9ee3-582429a90bec"},
    {"display_name": "CenterOps Hourly Snapshot 09", "schedule": "every day 09:00", "name": "projects/14417857267/locations/europe/transferConfigs/69970275-0000-2a76-92bb-d4f547ee8dd8"},
    {"display_name": "CenterOps Hourly Snapshot 10", "schedule": "every day 10:00", "name": "projects/14417857267/locations/europe/transferConfigs/6975ab51-0000-21e1-8f09-582429bd15a4"},
    {"display_name": "CenterOps Hourly Snapshot 11", "schedule": "every day 11:00", "name": "projects/14417857267/locations/europe/transferConfigs/6989e04f-0000-26c7-855b-3c286d48b47a"},
    {"display_name": "CenterOps Hourly Snapshot 12", "schedule": "every day 12:00", "name": "projects/14417857267/locations/europe/transferConfigs/699bb546-0000-2135-bdbb-582429bd47a8"},
    {"display_name": "CenterOps Hourly Snapshot 13", "schedule": "every day 13:00", "name": "projects/14417857267/locations/europe/transferConfigs/699a0b2c-0000-2962-b053-582429bd61a4"},
    {"display_name": "CenterOps Hourly Snapshot 14", "schedule": "every day 14:00", "name": "projects/14417857267/locations/europe/transferConfigs/6975f680-0000-2499-8e81-14c14ef708ac"},
    {"display_name": "CenterOps Hourly Snapshot 15", "schedule": "every day 15:00", "name": "projects/14417857267/locations/europe/transferConfigs/69635c0d-0000-2c33-93ba-c82add77e608"},
    {"display_name": "CenterOps Hourly Snapshot 16", "schedule": "every day 16:00", "name": "projects/14417857267/locations/europe/transferConfigs/699bfc4d-0000-21e4-98ad-582429a78fe8"},
    {"display_name": "CenterOps Hourly Snapshot 17", "schedule": "every day 17:00", "name": "projects/14417857267/locations/europe/transferConfigs/6975c441-0000-2182-9a69-582429bd19e4"},
    {"display_name": "CenterOps Hourly Snapshot 18", "schedule": "every day 18:00", "name": "projects/14417857267/locations/europe/transferConfigs/6975fbec-0000-2e52-9974-d4f547ee0d64"},
    {"display_name": "CenterOps Hourly Snapshot 19", "schedule": "every day 19:00", "name": "projects/14417857267/locations/europe/transferConfigs/698f3e4d-0000-2afe-ae75-582429a9d330"},
    {"display_name": "CenterOps Hourly Snapshot 20", "schedule": "every day 20:00", "name": "projects/14417857267/locations/europe/transferConfigs/6975f6ab-0000-2499-8e81-14c14ef708ac"},
    {"display_name": "CenterOps Hourly Snapshot 21", "schedule": "every day 21:00", "name": "projects/14417857267/locations/europe/transferConfigs/699e0e68-0000-2870-9717-d4f547fe816c"},
    {"display_name": "CenterOps Hourly Snapshot 22", "schedule": "every day 22:00", "name": "projects/14417857267/locations/europe/transferConfigs/697f5f95-0000-28fd-b54b-d4f547eec504"},
    {"display_name": "CenterOps Hourly Snapshot 23", "schedule": "every day 23:00", "name": "projects/14417857267/locations/europe/transferConfigs/69600e40-0000-29e4-960f-fc41166c9449"},
]


def load_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_params(sql: str) -> struct_pb2.Struct:
    params = {
        "query": sql,
        "destination_table_name_template": DEST_TABLE_TEMPLATE,
        "write_disposition": WRITE_DISPOSITION,
    }
    struct = struct_pb2.Struct()
    struct.update(params)
    return struct


def update_configs(client: bigquery_datatransfer_v1.DataTransferServiceClient, configs: Iterable[dict], params_struct: struct_pb2.Struct) -> None:
    mask = field_mask_pb2.FieldMask(paths=["params"])
    for cfg in configs:
        transfer_config = bigquery_datatransfer_v1.TransferConfig(
            name=cfg["name"],
            params=params_struct,
        )
        updated = client.update_transfer_config(
            transfer_config=transfer_config,
            update_mask=mask,
        )
        print(f"Updated {cfg['display_name']}: {updated.name}")


def main() -> None:
    gcloud_cmd = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not gcloud_cmd:
        raise SystemExit("gcloud not found in PATH; please ensure Cloud SDK is installed")
    token = subprocess.check_output([gcloud_cmd, "auth", "print-access-token"], text=True).strip()
    creds = Credentials(token=token)
    client = bigquery_datatransfer_v1.DataTransferServiceClient(credentials=creds)

    sql = load_sql(SQL_PATH)
    params_struct = build_params(sql)

    update_configs(client, CONFIGS, params_struct)


if __name__ == "__main__":
    main()
