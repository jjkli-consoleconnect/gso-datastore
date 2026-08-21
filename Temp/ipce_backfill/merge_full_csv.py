"""Merge TXCEAllTickets.csv into GSO.JiraTickets (CSV = source of truth).

Per user: if data is missing from the table, merge the CSV in; the CSV is
authoritative. Full upsert: UPDATE existing + INSERT missing TXCE rows.
"""
import csv, os, sys, json, datetime
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"

PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TARGET = f"{PROJECT}.{DATASET}.{TABLE}"
TMP = f"{DATASET}.txce_csv_full_tmp"
PROJECT_VALUE = "Transmission TX-CE"

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
HKT = datetime.timezone(datetime.timedelta(hours=8))


def log(msg):
    with open(os.path.join(DIR, "txce_full_merge.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} {msg}\n")


def parse_dt(s):
    """Parse 'Aug 20, 2026 22:37' (HKT local) -> ISO UTC string, or None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        p = s.split()
        if len(p) < 4:
            return None
        mon = MONTHS[p[0]]
        day = int(p[1].rstrip(","))
        yr = int(p[2])
        hm = p[3].split(":")
        hr, mi = int(hm[0]), int(hm[1])
        local = datetime.datetime(yr, mon, day, hr, mi, tzinfo=HKT)
        return local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        return None


def serialize_csv():
    jsonl = os.path.join(DIR, "txce_full_merge.jsonl")
    n = 0
    with open(CSV, "r", encoding="utf-8-sig", newline="") as f, \
         open(jsonl, "w", encoding="utf-8") as out:
        for r in csv.DictReader(f):
            key = (r.get("Issue key") or "").strip()
            if not key:
                continue
            rec = {
                "T": (r.get("Issue Type") or "").strip() or None,
                "Project": PROJECT_VALUE,
                "Key": key,
                "Summary": (r.get("Summary") or "").strip() or None,
                "Status": (r.get("Status") or "").strip() or None,
                "Created": parse_dt(r.get("Created")),
                "Updated": parse_dt(r.get("Updated")),
                "Resolved": parse_dt(r.get("Resolved")),
                "Reporter": (r.get("Reporter") or "").strip() or None,
                "Assignee": (r.get("Assignee") or "").strip() or None,
                "Creator": (r.get("Creator") or "").strip() or None,
                "Priority": (r.get("Priority") or "").strip() or None,
                "IssueId": (r.get("Issue id") or "").strip() or None,
                "ReporterId": (r.get("Reporter Id") or "").strip() or None,
                "AssigneeId": (r.get("Assignee Id") or "").strip() or None,
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"CSV rows serialized: {n}")
    log(f"CSV rows serialized: {n}")
    return jsonl

def load_merge_verify(client, jsonl):
    schema = [
        bigquery.SchemaField("T", "STRING"), bigquery.SchemaField("Project", "STRING"),
        bigquery.SchemaField("Key", "STRING"), bigquery.SchemaField("Summary", "STRING"),
        bigquery.SchemaField("Status", "STRING"), bigquery.SchemaField("Created", "TIMESTAMP"),
        bigquery.SchemaField("Updated", "TIMESTAMP"), bigquery.SchemaField("Resolved", "TIMESTAMP"),
        bigquery.SchemaField("Reporter", "STRING"), bigquery.SchemaField("Assignee", "STRING"),
        bigquery.SchemaField("Creator", "STRING"), bigquery.SchemaField("Priority", "STRING"),
        bigquery.SchemaField("IssueId", "STRING"), bigquery.SchemaField("ReporterId", "STRING"),
        bigquery.SchemaField("AssigneeId", "STRING"),
    ]
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    with open(jsonl, "rb") as fh:
        load_job = client.load_table_from_file(
            fh, f"{PROJECT}.{TMP}",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.job.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
        load_job.result()
    print(f"temp loaded rows: {load_job.output_rows}")
    log(f"temp loaded rows: {load_job.output_rows}")

    merge_sql = f"""
        MERGE `{TARGET}` T
        USING (SELECT DISTINCT * FROM `{PROJECT}.{TMP}`) S
        ON T.Key = S.Key
        WHEN MATCHED THEN UPDATE SET
            T.T = S.T, T.Project = S.Project, T.Summary = S.Summary, T.Status = S.Status,
            T.Created = S.Created, T.Updated = S.Updated, T.Resolved = S.Resolved,
            T.Reporter = S.Reporter, T.Assignee = S.Assignee, T.Creator = S.Creator,
            T.Priority = S.Priority, T.IssueId = S.IssueId,
            T.ReporterId = S.ReporterId, T.AssigneeId = S.AssigneeId
        WHEN NOT MATCHED THEN INSERT
            (T, Project, Key, Summary, Status, Created, Updated, Resolved,
             Reporter, Assignee, Creator, Priority, IssueId, ReporterId, AssigneeId)
        VALUES
            (S.T, S.Project, S.Key, S.Summary, S.Status, S.Created, S.Updated, S.Resolved,
             S.Reporter, S.Assignee, S.Creator, S.Priority, S.IssueId, S.ReporterId, S.AssigneeId)
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    print(f"merge affected rows (updates + inserts): {merge_job.num_dml_affected_rows}")
    log(f"merge affected rows: {merge_job.num_dml_affected_rows}")

    v = list(client.query(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN Creator IS NULL OR TRIM(Creator)='' THEN 1 ELSE 0 END) AS still_null "
        f"FROM `{TARGET}` WHERE Key LIKE 'TXCE-%'").result())[0]
    print(f"\nVERIFY TXCE: total={v.total} still_null_creator={v.still_null}")
    log(f"VERIFY TXCE total={v.total} still_null_creator={v.still_null}")

    os.remove(jsonl)
    client.delete_table(f"{PROJECT}.{TMP}", not_found_ok=True)
    print("CLEANUP DONE")


if __name__ == "__main__":
    client = get_client(PROJECT)
    jsonl = serialize_csv()
    load_merge_verify(client, jsonl)
