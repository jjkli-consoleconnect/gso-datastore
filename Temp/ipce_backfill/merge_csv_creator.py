"""Merge Creator values from TXCEAllTickets.csv into GSO.JiraTickets, then verify.

Strategy:
  * Read the CSV (authoritative source), extract Key + Creator into a JSONL.
  * Load JSONL into a temp BQ table.
  * MERGE into JiraTickets: WHEN MATCHED UPDATE SET Creator = S.Creator
    (covers every TXCE key present in both CSV and BQ; overwrite is fine).
  * Verify: count remaining NULL creators among TXCE rows in BQ, and
    report any BQ TXCE keys missing from the CSV (can't be fixed from CSV).
"""
import csv, io, json, os, sys, time
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"
KEY_PREFIX = "TXCE"
PROJECT_VALUE = "Transmission TX-CE"

PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TARGET = f"{PROJECT}.{DATASET}.{TABLE}"
TMP = f"{DATASET}.txce_csv_backfill_tmp"


def log(msg):
    with open(os.path.join(DIR, "txce_merge.log"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def main():
    client = get_client(PROJECT)

    # 1) Read CSV -> key->creator map, write JSONL
    jsonl = os.path.join(DIR, "txce_creator_merge.jsonl")
    key_to_creator = {}
    with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            k = (r.get("Issue key") or "").strip()
            c = (r.get("Creator") or "").strip() or None
            if not k:
                continue
            key_to_creator[k] = c
    with open(jsonl, "w", encoding="utf-8") as f:
        for k, c in key_to_creator.items():
            f.write(json.dumps({"Key": k, "Creator": c}, ensure_ascii=False) + "\n")
    print(f"CSV rows parsed: {len(key_to_creator)}")
    log(f"CSV rows parsed: {len(key_to_creator)}")

    # 2) Load temp table
    schema = [
        bigquery.SchemaField("Key", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Creator", "STRING", mode="NULLABLE"),
    ]
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    with open(jsonl, "rb") as fh:
        load_job = client.load_table_from_file(
            fh, f"{PROJECT}.{TMP}",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.job.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
        load_job.result()
    print(f"temp loaded rows: {load_job.output_rows}")
    log(f"temp loaded rows: {load_job.output_rows}")

    # 3) MERGE update Creator only for matching keys
    merge_sql = f"""
        MERGE `{TARGET}` T
        USING (
            SELECT DISTINCT Key, Creator FROM `{PROJECT}.{TMP}`
            WHERE Key LIKE '{KEY_PREFIX}-%' AND Creator IS NOT NULL
        ) S
        ON T.Key = S.Key
        WHEN MATCHED THEN UPDATE SET T.Creator = S.Creator
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    print(f"merge affected rows: {merge_job.num_dml_affected_rows}")
    log(f"merge affected rows: {merge_job.num_dml_affected_rows}")

    # 4) Verify remaining NULL creators + BQ keys not covered by CSV
    verify_sql = f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN Creator IS NULL OR TRIM(Creator) = '' THEN 1 ELSE 0 END) AS still_null
        FROM `{TARGET}`
        WHERE Key LIKE '{KEY_PREFIX}-%'
    """
    r = list(client.query(verify_sql).result())[0]
    print(f"\nVERIFY TXCE: total={r.total} still_null={r.still_null}")
    log(f"VERIFY TXCE: total={r.total} still_null={r.still_null}")

    # which BQ TXCE keys are NOT in the CSV -> these keep null (can't fix from CSV)
    bq_keys = {row.Key for row in client.query(
        f"SELECT DISTINCT Key FROM `{TARGET}` WHERE Key LIKE '{KEY_PREFIX}-%'").result()}
    missing = sorted(k for k in bq_keys if k not in key_to_creator)
    print(f"BQ TXCE keys total={len(bq_keys)}; not present in CSV (unfixable)= {len(missing)}")
    print("  sample missing:", missing[:10])
    # still-null keys specifically
    null_keys = [row.Key for row in client.query(
        f"SELECT Key FROM `{TARGET}` "
        f"WHERE Key LIKE '{KEY_PREFIX}-%' AND (Creator IS NULL OR TRIM(Creator)='')").result()]
    print(f"keys still NULL after merge: {len(null_keys)}")

    # 5) cleanup
    os.remove(jsonl)
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    print("CLEANUP DONE")


if __name__ == "__main__":
    main()