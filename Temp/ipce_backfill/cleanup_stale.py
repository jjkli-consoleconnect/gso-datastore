"""Scope-cleanup for GSO.JiraTickets TXCE rows.

The merge (merge_allfields.py) populated Creator/Resolution/Description/etc.
for the 7267 rows present in TXCEAllFields.csv. The remaining TXCE rows whose
Key is NOT in that CSV are stale artifacts from the prior creator.csv backfill
(incl. 2401 rows with a NULL Key -- unusable, no Jira issue is keyless). This
script rebuilds only the CSV key set and DELETEs those stray TXCE rows so the
table exactly matches the source-of-truth CSV. Other projects are untouched.
"""
import csv, os, sys, datetime, json
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery
from google.cloud import bigquery as bq

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TARGET = f"{PROJECT}.{DATASET}.{TABLE}"
TMP = f"{DATASET}.txce_keys_tmp"


def log(msg):
    with open(os.path.join(DIR, "txce_cleanup.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} {msg}\n")


def csv_keys():
    keys = set()
    with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        headers = next(rd)
        ki = None
        for i, h in enumerate(headers):
            if h == "Issue key":
                ki = i
                break
        if ki is None:
            raise SystemExit("Issue key column not found in CSV headers")
        for row in rd:
            if ki < len(row) and (row[ki] or "").strip():
                keys.add(row[ki].strip())
    return keys


def main():
    keys = csv_keys()
    print(f"CSV TXCE keys collected: {len(keys)}")
    log(f"CSV TXCE keys collected: {len(keys)}")

    client = get_client(PROJECT)
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    schema = [bq.SchemaField("Key", "STRING")]
    job_config = bq.LoadJobConfig(
        schema=schema,
        source_format=bq.job.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bq.WriteDisposition.WRITE_TRUNCATE,
    )
    tmp_path = os.path.join(DIR, "_txce_keys_tmp.jsonl")
    with open(tmp_path, "w", encoding="utf-8") as out:
        for k in keys:
            out.write(json.dumps({"Key": k}) + "\n")
    with open(tmp_path, "rb") as fh:
        job = client.load_table_from_file(fh, f"{PROJECT}.{TMP}", job_config=job_config)
        job.result()
    print(f"temp keys loaded: {job.output_rows}")
    log(f"temp keys loaded: {job.output_rows}")
    os.remove(tmp_path)

    # Scoped delete: TXCE rows whose Key is absent from the CSV key set.
    # Key IS NULL covers the 2401 keyless artifacts; NOT IN covers the 5.
    delete_sql = f"""
        DELETE FROM `{TARGET}`
        WHERE Project = 'Transmission TX-CE'
          AND (Key IS NULL OR Key NOT IN (SELECT Key FROM `{PROJECT}.{TMP}` WHERE Key IS NOT NULL))
    """
    del_job = client.query(delete_sql)
    del_job.result()
    print(f"scoped DELETE affected rows: {del_job.num_dml_affected_rows}")
    log(f"scoped DELETE affected rows: {del_job.num_dml_affected_rows}")

    # Final reconciliation: TXCE row count must equal CSV key count.
    v = list(client.query(
        f"SELECT COUNT(*) AS total, COUNTIF(Creator IS NOT NULL AND CREATOR != '') AS has_creator "
        f"FROM `{TARGET}` WHERE Project = 'Transmission TX-CE'").result())[0]
    print(f"VERIFY final: txce_total={v.total} has_creator={v.has_creator} csv_keys={len(keys)}")
    log(f"VERIFY final txce_total={v.total} has_creator={v.has_creator} csv_keys={len(keys)}")

    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    print("CLEANUP DONE")
    log("CLEANUP DONE")


if __name__ == "__main__":
    main()
