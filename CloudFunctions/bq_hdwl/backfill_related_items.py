"""
One-off backfill: populate RelatedItem* ARRAY<STRING> fields in
pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC from a related-items CSV.

CSV format (one row per related item, header row required):
  IncidentNumber,RelatedItemRequestID,RelatedItemDescription,RelatedItemRelatedTicketID,RelatedItemAssociationType

Behavior:
  - Loads CSV to a run-scoped temp BQ table (all STRING).
  - MERGEs into target: for matching incidents, replaces the 4 array fields
    with ARRAY_AGG of the CSV values (NULLs/empties skipped).
  - Other fields untouched. Incidents not in target are reported and skipped.
  - Temp table deleted afterwards.

Usage:
  python backfill_related_items.py --csv "path\\to\\file.csv" [--dry-run]

Safe to re-run (idempotent).
"""

import argparse
import csv
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_related_items")

PROJECT_ID = "pccw-internal-virt-agent-uat"
TARGET_TABLE = f"{PROJECT_ID}.GSO.HelpDeskAllNOC"

FIELD_COLUMNS = [
    "RelatedItemRequestID",
    "RelatedItemDescription",
    "RelatedItemRelatedTicketID",
    "RelatedItemAssociationType",
]

PREVIEW_DELIM = " || "


def read_and_validate_csv(csv_path: str):
    """Read CSV, return (rows, skipped_count). Rows are dicts keyed by header name."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    rows = []
    skipped = 0
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        required = ["IncidentNumber"] + FIELD_COLUMNS
        missing = [c for c in required if c not in headers]
        if missing:
            raise ValueError(f"CSV missing required headers: {missing}. Found: {headers}")

        for raw in reader:
            raw.pop(None, None)  # drop overflow columns from rows with extra fields
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if not row.get("IncidentNumber", ""):
                skipped += 1
                continue
            if all(not row.get(c, "") for c in FIELD_COLUMNS):
                skipped += 1
                continue
            rows.append(row)

    logger.info("Read %d valid rows from %s (%d skipped)", len(rows), csv_path, skipped)
    return rows, skipped


def run_dry_run(rows):
    """Print what would be written, grouped per incident."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["IncidentNumber"], []).append(row)

    logger.info("DRY RUN: %d incidents would be updated.", len(grouped))
    for i, (incident, items) in enumerate(list(grouped.items())[:10]):
        logger.info(
            "  %s -> %d item(s): req=[%s] assoc=[%s] desc=[%s]",
            incident,
            len(items),
            PREVIEW_DELIM.join(filter(None, (r["RelatedItemRequestID"] for r in items)))[:60],
            PREVIEW_DELIM.join(filter(None, (r["RelatedItemAssociationType"] for r in items)))[:30],
            PREVIEW_DELIM.join(filter(None, (r["RelatedItemDescription"] for r in items)))[:60],
        )
        if i >= 9:
            logger.info("  ... (%d more incidents)", len(grouped) - 10)


def upload_to_temp_table(bq_client: bigquery.Client, csv_path: str) -> str:
    """Upload CSV to a temp table, all fields STRING, one row per related item."""
    table_id = (
        f"{PROJECT_ID}.Staging.RelatedItemsBackfill_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )

    schema = [bigquery.SchemaField("IncidentNumber", "STRING", mode="REQUIRED")]
    schema += [bigquery.SchemaField(c, "STRING", mode="NULLABLE") for c in FIELD_COLUMNS]

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=False,
        schema=schema,
        skip_leading_rows=1,
        field_delimiter=",",
        allow_quoted_newlines=True,
    )

    with open(csv_path, "rb") as f:
        load_job = bq_client.load_table_from_file(f, table_id, job_config=job_config)
    load_job.result()
    logger.info("Loaded CSV to temp table %s", table_id)
    return table_id


def run_backfill(bq_client: bigquery.Client, temp_table_id: str):
    """MERGE arrays into target table. Other fields untouched."""

    def agg(col: str) -> str:
        return (
            f"(SELECT ARRAY_AGG(x IGNORE NULLS ORDER BY x) "
            f"FROM UNNEST(ARRAY_AGG(DISTINCT NULLIF(S.{col}, ''))) AS x)"
        )

    coverage_query = f"""
        SELECT
            (SELECT COUNT(DISTINCT IncidentNumber) FROM `{temp_table_id}`) AS csv_incidents,
            (SELECT COUNT(DISTINCT s.IncidentNumber) FROM `{temp_table_id}` s
             JOIN `{TARGET_TABLE}` t ON t.Incident_Number = s.IncidentNumber) AS matched
    """
    stats = list(bq_client.query(coverage_query).result())[0]
    logger.info(
        "CSV covers %d incidents; %d match existing target rows.",
        stats.csv_incidents,
        stats.matched,
    )
    if stats.csv_incidents - stats.matched > 0:
        logger.warning(
            "%d incident(s) in CSV not found in target table; they will be skipped.",
            stats.csv_incidents - stats.matched,
        )

    merge_query = f"""
    MERGE `{TARGET_TABLE}` T
    USING (
        SELECT
            IncidentNumber,
            {agg('RelatedItemRequestID')} AS RelatedItemRequestID,
            {agg('RelatedItemDescription')} AS RelatedItemDescription,
            {agg('RelatedItemRelatedTicketID')} AS RelatedItemRelatedTicketID,
            {agg('RelatedItemAssociationType')} AS RelatedItemAssociationType
        FROM `{temp_table_id}` AS S
        GROUP BY S.IncidentNumber
    ) S
    ON T.Incident_Number = S.IncidentNumber
    WHEN MATCHED THEN
        UPDATE SET
            T.RelatedItemRequestID = S.RelatedItemRequestID,
            T.RelatedItemDescription = S.RelatedItemDescription,
            T.RelatedItemRelatedTicketID = S.RelatedItemRelatedTicketID,
            T.RelatedItemAssociationType = S.RelatedItemAssociationType
    """
    job = bq_client.query(merge_query)
    job.result()
    logger.info("MERGE complete. Target rows updated: %s", job.num_dml_affected_rows)


def verify_arrays_exist(bq_client: bigquery.Client) -> bool:
    """Check the 4 target columns exist as REPEATED (ARRAY) STRING."""
    table = bq_client.get_table(TARGET_TABLE)
    fields = {f.name: f for f in table.schema}
    problems = []
    for col in FIELD_COLUMNS:
        field = fields.get(col)
        if field is None:
            problems.append(f"{col}: missing")
        elif field.mode != "REPEATED" or field.field_type != "STRING":
            problems.append(f"{col}: mode={field.mode} type={field.field_type} (expected REPEATED STRING)")
    if problems:
        logger.error("Target table column check failed: %s", "; ".join(problems))
        logger.error(
            "Run this first:\n  ALTER TABLE `%s`\n%s",
            TARGET_TABLE,
            "\n".join(f"    ADD COLUMN {c} ARRAY<STRING>;" for c in FIELD_COLUMNS),
        )
        return False
    return True


def cleanup(bq_client: bigquery.Client, temp_table_id: str):
    try:
        bq_client.delete_table(temp_table_id, not_found_ok=True)
        logger.info("Deleted temp table %s", temp_table_id)
    except Exception as e:
        logger.warning("Failed to delete temp table %s: %s", temp_table_id, e)


def main():
    parser = argparse.ArgumentParser(description="Backfill RelatedItem* arrays into HelpDeskAllNOC")
    parser.add_argument("--csv", required=True, help="Path to the related-items CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    bq_client = None if args.dry_run else bigquery.Client(project=PROJECT_ID)

    rows, _skipped = read_and_validate_csv(args.csv)
    if not rows:
        logger.error("No valid rows to backfill. Exiting.")
        sys.exit(1)

    if args.dry_run:
        run_dry_run(rows)
        logger.info("Dry run complete. No changes made.")
        return

    if not verify_arrays_exist(bq_client):
        logger.error("Fix target table schema first. Exiting.")
        sys.exit(1)

    temp_table_id = None
    try:
        temp_table_id = upload_to_temp_table(bq_client, args.csv)
        run_backfill(bq_client, temp_table_id)
    finally:
        if temp_table_id:
            cleanup(bq_client, temp_table_id)

    logger.info("Backfill finished.")


if __name__ == "__main__":
    main()

