from __future__ import annotations

import argparse
import csv
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.cloud import bigquery
from google.oauth2.credentials import Credentials


PROJECT_ID = "pccw-internal-virt-agent-uat"
DATASET_ID = "GSO"
TABLE_ID = "JiraTickets"
DEFAULT_CSV = Path(__file__).resolve().parent / "TXCEAllTickets.csv"
LABELS = {"datacloud": "vscode"}


CSV_TO_BQ = {
    "Issue Type": "T",
    "Issue key": "Key",
    "Issue id": "IssueId",
    "Summary": "Summary",
    "Assignee": "Assignee",
    "Assignee Id": "AssigneeId",
    "Reporter": "Reporter",
    "Reporter Id": "ReporterId",
    "Status": "Status",
    "Created": "Created",
    "Creator": "Creator",
    "Updated": "Updated",
    "Resolved": "Resolved",
    "Priority": "Priority",
    "Components": "Component",
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower() in {"nan", "none", "null"}:
        return None
    return value


def parse_jira_datetime(value: str | None) -> datetime | None:
    value = clean_text(value)
    if not value:
        return None
    for fmt in ("%b %d, %Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"Unsupported datetime value: {value!r}")


def format_bq_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def split_repeated(value: str | None) -> list[str]:
    value = clean_text(value)
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]


def read_csv_rows(csv_path: Path, project_name: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
        label_indexes = [idx for idx, name in enumerate(headers) if name == "Labels"]
        mapped_indexes = {
            idx: CSV_TO_BQ[name]
            for idx, name in enumerate(headers)
            if name in CSV_TO_BQ
        }

        for raw in reader:
            row: dict[str, Any] = {}
            for idx, bq_name in mapped_indexes.items():
                value = raw[idx] if idx < len(raw) else None
                if bq_name in {"Created", "Updated", "Resolved"}:
                    row[bq_name] = format_bq_timestamp(parse_jira_datetime(value))
                elif bq_name == "Component":
                    row[bq_name] = split_repeated(value)
                else:
                    row[bq_name] = clean_text(value)

            labels = []
            for idx in label_indexes:
                labels.extend(split_repeated(raw[idx] if idx < len(raw) else None))
            row["Labels"] = list(dict.fromkeys(labels))
            row["SyncTime"] = format_bq_timestamp(datetime.now(timezone.utc))
            row["IsDeleted"] = False
            row["DeletedAt"] = None
            if project_name:
                row["Project"] = project_name

            if row.get("Key"):
                rows.append(row)

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["Key"]
        current = deduped.get(key)
        if current is None or (row.get("Updated") or "") >= (current.get("Updated") or ""):
            deduped[key] = row
    return list(deduped.values())


def build_stage_schema(target_schema: list[bigquery.SchemaField], rows: list[dict[str, Any]]) -> list[bigquery.SchemaField]:
    target_fields = {field.name: field for field in target_schema}
    stage_fields = []
    for name in rows[0].keys():
        field = target_fields[name]
        mode = "REQUIRED" if name == "Key" else field.mode
        stage_fields.append(bigquery.SchemaField(name, field.field_type, mode=mode))
    return stage_fields


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_query(client: bigquery.Client, sql: str) -> bigquery.table.RowIterator:
    job_config = bigquery.QueryJobConfig(labels=LABELS)
    return client.query(sql, job_config=job_config).result()


def merge_rows(
    client: bigquery.Client,
    full_table_id: str,
    stage_table_id: str,
    columns: list[str],
    source_prefixes: list[str],
    execute: bool,
) -> None:
    mutable_columns = [name for name in columns if name != "Key"]
    update_set = ",\n        ".join(f"T.{name} = S.{name}" for name in mutable_columns)
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"S.{name}" for name in columns)
    target_prefix_filter = " OR ".join(f"STARTS_WITH(T.Key, {sql_literal(prefix + '-')})" for prefix in source_prefixes)
    update_prefix_filter = " OR ".join(f"STARTS_WITH(target.Key, {sql_literal(prefix + '-')})" for prefix in source_prefixes)

    before_sql = f"""
    SELECT
      COUNTIF(S.Key IS NOT NULL) AS matched_rows,
      COUNTIF(S.Key IS NULL) AS missing_from_csv_rows,
      COUNT(*) AS target_scope_rows
    FROM `{full_table_id}` T
    LEFT JOIN `{stage_table_id}` S
    ON T.Key = S.Key
    WHERE ({target_prefix_filter})
    """
    for row in run_query(client, before_sql):
        print(
            "target_scope_rows={target_scope_rows} matched_rows={matched_rows} missing_from_csv_rows={missing_from_csv_rows}".format(
                **dict(row)
            )
        )

    new_rows_sql = f"""
    SELECT COUNT(*) AS new_rows
    FROM `{stage_table_id}` S
    LEFT JOIN `{full_table_id}` T
    ON T.Key = S.Key
    WHERE T.Key IS NULL
    """
    for row in run_query(client, new_rows_sql):
        print(f"new_rows={row.new_rows}")

    if not execute:
        print("dry_run=true no changes applied")
        return

    merge_sql = f"""
    MERGE `{full_table_id}` T
    USING `{stage_table_id}` S
    ON T.Key = S.Key
    WHEN MATCHED THEN UPDATE SET
        {update_set}
    WHEN NOT MATCHED THEN
      INSERT ({insert_columns})
      VALUES ({insert_values})
    """
    merge_job = client.query(merge_sql, job_config=bigquery.QueryJobConfig(labels=LABELS))
    merge_job.result()
    print(f"merge_affected_rows={merge_job.num_dml_affected_rows or 0}")

    delete_sql = f"""
        UPDATE `{full_table_id}` AS target
    SET IsDeleted = TRUE,
        DeletedAt = CURRENT_TIMESTAMP(),
        SyncTime = CURRENT_TIMESTAMP()
        WHERE ({update_prefix_filter})
      AND NOT EXISTS (
                SELECT 1 FROM `{stage_table_id}` S WHERE S.Key = target.Key
      )
      AND COALESCE(IsDeleted, FALSE) = FALSE
    """
    delete_job = client.query(delete_sql, job_config=bigquery.QueryJobConfig(labels=LABELS))
    delete_job.result()
    print(f"marked_deleted_rows={delete_job.num_dml_affected_rows or 0}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge a Jira CSV export into GSO.JiraTickets by issue key.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="CSV export path.")
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--table", default=TABLE_ID)
    parser.add_argument("--project-name", default="Transmission TX-CE")
    parser.add_argument("--execute", action="store_true", help="Apply the merge. Omit for validation only.")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    rows = read_csv_rows(csv_path, args.project_name)
    if not rows:
        raise ValueError(f"No rows with Issue key found in {csv_path}")

    key_prefixes = sorted({row["Key"].split("-", 1)[0] for row in rows if "-" in row["Key"]})
    if not key_prefixes:
        raise ValueError("Could not infer Jira key prefix scope from CSV")

    duplicate_count = sum(count - 1 for count in Counter(row["Key"] for row in rows).values() if count > 1)
    print(f"csv_rows={len(rows)} duplicate_keys_dropped={duplicate_count} key_prefixes={','.join(key_prefixes)}")

    token = os.environ.get("JIRA_DATAPIPE_ACCESS_TOKEN") or os.environ.get("GCLOUD_ACCESS_TOKEN")
    credentials = Credentials(token) if token else None
    client = bigquery.Client(project=args.project, credentials=credentials)
    full_table_id = f"{args.project}.{args.dataset}.{args.table}"
    target_table = client.get_table(full_table_id)
    target_names = {field.name for field in target_table.schema}
    missing = sorted(set(rows[0].keys()) - target_names)
    if missing:
        raise ValueError(f"Mapped columns missing from target schema: {missing}")

    stage_table_id = f"{args.project}.{args.dataset}._stg_jiratickets_csv_{uuid.uuid4().hex[:8]}"
    stage_schema = build_stage_schema(target_table.schema, rows)
    load_config = bigquery.LoadJobConfig(
        schema=stage_schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        labels=LABELS,
    )

    try:
        load_job = client.load_table_from_json(rows, stage_table_id, job_config=load_config)
        load_job.result()
        print(f"staged_rows={client.get_table(stage_table_id).num_rows} stage_table={stage_table_id}")
        merge_rows(client, full_table_id, stage_table_id, list(rows[0].keys()), key_prefixes, args.execute)
    finally:
        client.delete_table(stage_table_id, not_found_ok=True)


if __name__ == "__main__":
    main()