from pathlib import Path

from google.cloud import bigquery_datatransfer_v1
from google.protobuf import field_mask_pb2, struct_pb2

TRANSFER_CONFIG = "projects/14417857267/locations/europe-west2/transferConfigs/6a293222-0000-2a3f-b18f-94eb2c1cf75e"
QUERY_PATH = Path(r"G:\My Drive\Scripts\BigQuery\pccw-internal-virt-agent-uat\GSOEDPLink\scheduled_queries\CostItemSnapSnapshot.sql")


def main() -> None:
    query_text = QUERY_PATH.read_text(encoding="utf-8")

    client = bigquery_datatransfer_v1.DataTransferServiceClient()
    config = client.get_transfer_config(name=TRANSFER_CONFIG)

    params = struct_pb2.Struct()
    params.update(dict(config.params))
    params.update(
        {
            "destination_table_name_template": "CostItemSnapSnapshot",
            "query": query_text,
            "write_disposition": "WRITE_APPEND",
        }
    )
    config.params = params

    update_mask = field_mask_pb2.FieldMask(paths=["params"])
    updated = client.update_transfer_config(
        transfer_config=config,
        update_mask=update_mask,
    )

    query_value = dict(updated.params).get("query", "")
    print("UPDATED_NAME:", updated.name)
    print("HAS_V4_MARKER:", "v4_2026_07_16" in query_value)
    print(
        "HAS_START_VIEW_ESTIMATED_COST_FORMULA:",
        "ROUND(SUM(IF(OpenStartGapFlag = 1, EstimatedStartGapCostUSD, 0)), 1) AS estimated_gap_cost_usd" in query_value,
    )


if __name__ == "__main__":
    main()
