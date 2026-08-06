import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List

from google.cloud import bigquery

PROJECT_ID = "pccw-internal-virt-agent-uat"

CONFIGS = {
    "helpdesk": {
        "name": "HelpDeskAllNOC",
        "target_dataset": "GSO",
        "target_table": "HelpDeskAllNOC",
        "primary_key": "Incident_Number",
        "all_columns": [
            "Incident_Number", "Status", "CaseType", "Assigned_Group", "Categorization_Tier_1",
            "Categorization_Tier_2", "Categorization_Tier_3", "GCSC_1st_Customer_Update",
            "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update", "Initial_Response_Time",
            "Second_Response_Time", "Third_Response_Time", "Prod_ID", "Fault_Cause",
            "Closed_Date", "Submit_Date", "Assignee", "Closed_By", "Submitter", "TrueMTTR_mins",
            "Cust_ID", "Carrier", "Customer_Name", "SRno", "LastResolvedDate", "ReportedDate",
            "RespondedDate", "FaultCauseDetail", "LastModifiedDate", "ReportedBy",
            "Product_Family", "ProductDescription", "GSMP_Circuit_ID", "Urgency", "Priority",
            "RSMName"
        ],
        "field_map": {
            "IncidentNumber": "Incident_Number", "casetype": "CaseType", "Assigned Group": "Assigned_Group",
            "Categorization Tier 1": "Categorization_Tier_1", "Categorization Tier 2": "Categorization_Tier_2",
            "Categorization Tier 3": "Categorization_Tier_3", "GCSC 1st Customer Update": "GCSC_1st_Customer_Update",
            "GCSC 2nd Customer Update": "GCSC_2nd_Customer_Update", "GCSC 3rd Customer Update": "GCSC_3rd_Customer_Update",
            "Initial Response Time": "Initial_Response_Time", "Second Response Time": "Second_Response_Time",
            "Third Response Time": "Third_Response_Time", "Prod ID": "Prod_ID", "FaultCause": "Fault_Cause",
            "Closed Date": "Closed_Date", "Submit Date": "Submit_Date", "ClosedBy": "Closed_By",
            "Cust ID": "Cust_ID", "CustomerName": "Customer_Name", "SRNo": "SRno", "SRno": "SRno",
            "ReportedBy": "ReportedBy", "Product Family": "Product_Family", "ProductDescription": "ProductDescription",
            "GSMP Circuit ID": "GSMP_Circuit_ID", "RSMName": "RSMName"
        },
        "timestamp_fields": [
            "GCSC_1st_Customer_Update", "GCSC_2nd_Customer_Update", "GCSC_3rd_Customer_Update",
            "Closed_Date", "Submit_Date", "LastResolvedDate", "ReportedDate", "RespondedDate",
            "LastModifiedDate"
        ],
        "integer_fields": ["Initial_Response_Time", "Second_Response_Time", "Third_Response_Time", "TrueMTTR_mins"],
        "freshness_candidates": ["LastModifiedDate", "Submit_Date"],
    },
    "worklog": {
        "name": "WorkLog",
        "target_dataset": "GSO",
        "target_table": "WorkLogAllNOC",
        "primary_key": "WorkLog_ID",
        "all_columns": [
            "Incident_Number", "WorkLog_Type", "WorkLog_ID", "WorkLog_Submit_Date",
            "WorkLog_Submitter", "Last_Modified_Date", "Last_Modified_By", "ExtractedDescription"
        ],
        "field_map": {
            "IncidentNumber": "Incident_Number", "WorkLogType": "WorkLog_Type",
            "WorkLogID": "WorkLog_ID", "WorkLogSubmitDate": "WorkLog_Submit_Date",
            "WorkLogSubmitter": "WorkLog_Submitter", "LastModifiedDate": "Last_Modified_Date",
            "LastModifiedBy": "Last_Modified_By", "ExtractedDescription": "ExtractedDescription"
        },
        "timestamp_fields": ["WorkLog_Submit_Date", "Last_Modified_Date"],
        "integer_fields": [],
        "freshness_candidates": ["Last_Modified_Date", "WorkLog_Submit_Date"],
    },
}


def standardize_field_name(header: str, field_map: Dict[str, str]) -> str:
    normalized_header = header.strip().strip('"').strip("'")
    return field_map.get(normalized_header, normalized_header.replace(' ', '_'))


def normalize_rsm_name(value: Any) -> Any:
    """Convert surname-first comma-delimited RSM values into display order. Strips quotes."""
    if value is None:
        return None
    cleaned = str(value).strip().strip('"').strip("'")
    if not cleaned:
        return None
    parts = [part.strip() for part in cleaned.split(',') if part and part.strip()]
    if len(parts) < 2:
        return cleaned
    return ' '.join(parts[1:] + [parts[0]])


def handle_empty_values(value: Any, is_timestamp: bool, is_integer: bool) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    value_str = str(value).strip().strip('"')
    if not value_str:
        return None

    if is_integer:
        try:
            return int(value_str)
        except Exception:
            return None

    if is_timestamp:
        # Keep canonical timestamp string when parseable, otherwise pass raw string for SAFE_CAST at merge.
        patterns = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M",
        ]
        for pattern in patterns:
            try:
                dt = datetime.strptime(value_str, pattern)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

    return value_str


def read_and_map_rows(csv_path: Path, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows_out: List[Dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for src_row in reader:
            obj = {col: None for col in config["all_columns"]}
            for src_key, value in src_row.items():
                mapped = standardize_field_name(src_key, config["field_map"])
                if mapped not in obj:
                    continue
                normalized_value = handle_empty_values(
                    value,
                    mapped in config["timestamp_fields"],
                    mapped in config["integer_fields"],
                )
                if mapped == "RSMName":
                    normalized_value = normalize_rsm_name(normalized_value)
                obj[mapped] = normalized_value
            rows_out.append(obj)
    return rows_out


def get_columns(client: bigquery.Client, table_ref: str) -> List[str]:
    table = client.get_table(table_ref)
    return [f.name for f in table.schema]


def load_to_staging(client: bigquery.Client, rows: List[Dict[str, Any]], config: Dict[str, Any]) -> str:
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    staging_table = f"{PROJECT_ID}.Staging.manual_{config['target_table']}_{run_tag}"

    schema_type_map = {col: "STRING" for col in config["all_columns"]}
    for ts_col in config["timestamp_fields"]:
        schema_type_map[ts_col] = "TIMESTAMP"
    for int_col in config["integer_fields"]:
        schema_type_map[int_col] = "INT64"

    schema = [
        bigquery.SchemaField(name=col, field_type=schema_type_map[col], mode="NULLABLE")
        for col in config["all_columns"]
    ]

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=schema,
    )
    job = client.load_table_from_json(rows, staging_table, job_config=job_config)
    job.result()
    return staging_table


def merge_staging(client: bigquery.Client, config: Dict[str, Any], staging_table: str) -> int:
    target_table = f"{PROJECT_ID}.{config['target_dataset']}.{config['target_table']}"
    primary_key = config["primary_key"]

    staging_cols = get_columns(client, staging_table)
    target_cols = get_columns(client, target_table)
    target_cols_lookup = {c.lower(): c for c in target_cols}
    merge_cols = [target_cols_lookup[c.lower()] for c in staging_cols if c.lower() in target_cols_lookup]

    dedupe_col = next((c for c in config["freshness_candidates"] if c in merge_cols), primary_key)

    def source_expr(col: str) -> str:
        if col in config["timestamp_fields"]:
            return f"SAFE_CAST(H.{col} AS TIMESTAMP)"
        if col in config["integer_fields"]:
            return f"SAFE_CAST(H.{col} AS INT64)"
        return f"H.{col}"

    freshness_col = next((c for c in config["freshness_candidates"] if c in merge_cols), None)
    update_match_condition = "TRUE"
    if freshness_col:
        update_match_condition = (
            f"(H.{freshness_col} IS NOT NULL AND "
            f"(T.{freshness_col} IS NULL OR H.{freshness_col} >= T.{freshness_col}))"
        )

    deduped_source_query = f"""
    SELECT * EXCEPT(_rn)
    FROM (
      SELECT H.*, ROW_NUMBER() OVER (PARTITION BY H.{primary_key} ORDER BY H.{dedupe_col} DESC) AS _rn
      FROM `{staging_table}` H
      WHERE H.{primary_key} IS NOT NULL
    )
    WHERE _rn = 1
    """

    update_cols = [c for c in merge_cols if c != primary_key]
    update_set = ",".join([f"T.{c} = {source_expr(c)}" for c in update_cols])
    insert_cols = ",".join(merge_cols)
    insert_vals = ",".join([source_expr(c) for c in merge_cols])

    merge_sql = f"""
    MERGE `{target_table}` T
    USING ({deduped_source_query}) H
    ON T.{primary_key} = H.{primary_key}
    WHEN MATCHED AND {update_match_condition} THEN
      UPDATE SET {update_set}
    WHEN NOT MATCHED THEN
      INSERT ({insert_cols}) VALUES ({insert_vals})
    """

    job = client.query(merge_sql, job_config=bigquery.QueryJobConfig(use_legacy_sql=False))
    job.result()
    return int(job.num_dml_affected_rows or 0)


def run_one(client: bigquery.Client, csv_path: Path, kind: str) -> None:
    config = CONFIGS[kind]
    rows = read_and_map_rows(csv_path, config)
    print(f"[{kind}] Parsed rows: {len(rows)}")
    if not rows:
        print(f"[{kind}] No rows found; skipping")
        return

    staging = load_to_staging(client, rows, config)
    print(f"[{kind}] Loaded to staging: {staging}")
    try:
        affected = merge_staging(client, config, staging)
        print(f"[{kind}] Merge affected rows: {affected}")
    finally:
        client.delete_table(staging, not_found_ok=True)
        print(f"[{kind}] Deleted staging table")


if __name__ == "__main__":
    import glob

    csv_dir = Path(__file__).parent / "RSMName Backfill"
    csv_files = sorted(glob.glob(str(csv_dir / "HelpDesk*.csv")))

    if not csv_files:
        print(f"No CSV files found in {csv_dir}")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV files to process")
    client = bigquery.Client(project=PROJECT_ID)

    for i, csv_path_str in enumerate(csv_files, 1):
        csv_path = Path(csv_path_str)
        print(f"\n[{i}/{len(csv_files)}] Processing: {csv_path.name}")
        run_one(client, csv_path, "helpdesk")
        print(f"[{i}/{len(csv_files)}] Done: {csv_path.name}")
