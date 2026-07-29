from google.cloud import bigquery_datatransfer_v1
from google.protobuf import field_mask_pb2, struct_pb2

TRANSFER_CONFIG = "projects/14417857267/locations/europe/transferConfigs/6a33091c-0000-27ff-8aa4-001a114ce186"
TARGET_SCHEDULE = "every day 23:55"

QUERY_TEXT = """MERGE `pccw-internal-virt-agent-uat.GSO.SHRPeople_StatusMonthlyCounts` t
USING (
  SELECT
    DATE_TRUNC(CURRENT_DATE(), MONTH) AS snapshot_month,
    LAST_DAY(CURRENT_DATE(), MONTH) AS snapshot_date,
    COALESCE(NULLIF(TRIM(SR_Status), ''), 'Unknown') AS SR_Status,
    COALESCE(NULLIF(TRIM(Circuit_Owner), ''), 'Unknown') AS Circuit_Owner,
    COUNT(DISTINCT SRNo) AS sr_count,
    CURRENT_TIMESTAMP() AS updated_at
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE CURRENT_DATE() = LAST_DAY(CURRENT_DATE(), MONTH)
  GROUP BY 1,2,3,4
) s
ON t.snapshot_month = s.snapshot_month
AND t.SR_Status = s.SR_Status
AND t.Circuit_Owner = s.Circuit_Owner
WHEN MATCHED THEN UPDATE SET
  t.snapshot_date = s.snapshot_date,
  t.sr_count = s.sr_count,
  t.updated_at = s.updated_at
WHEN NOT MATCHED THEN INSERT (
  snapshot_month,
  snapshot_date,
  SR_Status,
  Circuit_Owner,
  sr_count,
  updated_at
) VALUES (
  s.snapshot_month,
  s.snapshot_date,
  s.SR_Status,
  s.Circuit_Owner,
  s.sr_count,
  s.updated_at
);
"""


def main() -> None:
    client = bigquery_datatransfer_v1.DataTransferServiceClient()
    config = client.get_transfer_config(name=TRANSFER_CONFIG)

    params = struct_pb2.Struct()
    params.update(dict(config.params))
    params.update(
        {
            "query": QUERY_TEXT,
        }
    )

    config.params = params
    config.schedule = TARGET_SCHEDULE

    update_mask = field_mask_pb2.FieldMask(paths=["params", "schedule"])
    updated = client.update_transfer_config(
        transfer_config=config,
        update_mask=update_mask,
    )

    updated_params = dict(updated.params)
    query_value = str(updated_params.get("query", ""))

    print("UPDATED_NAME:", updated.name)
    print("UPDATED_SCHEDULE:", updated.schedule)
    print("HAS_PREV_DAY_LOGIC:", "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)" in query_value)
    print("HAS_MONTH_END_WHERE_FILTER:", "WHERE CURRENT_DATE() = LAST_DAY(CURRENT_DATE(), MONTH)" in query_value)


if __name__ == "__main__":
    main()
