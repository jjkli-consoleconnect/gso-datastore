"""Backfill JiraTickets for IPCE from Jira "all fields" CSV export.
Maps CSV columns -> BQ columns where a clean mapping exists; ignores the rest.
Timestamps interpreted as Asia/Hong_Kong and converted to UTC (matches Jira API truth).
"""
import csv, io, os, json, sys, time, logging
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery
import gcloud_auth

CSV = r"g:\My Drive\Scripts\Temp\IPCETicketComments.csv"
PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TMP = "JiraTickets_backfill_temp"
LOG = r"g:\My Drive\Scripts\Temp\ipce_backfill\tickets.log"

logging.basicConfig(filename=LOG, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
HKTZ = timezone(timedelta(hours=8))
SYNC_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def parse_dt(val):
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def to_utc_ts(val):
    dt = parse_dt(val)
    if dt is None:
        return None
    dt = dt.replace(tzinfo=HKTZ)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def parse_date(val):
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d/%b/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def clean(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None

def read_csv():
    f = open(CSV, "r", encoding="utf-8-sig", newline="")
    r = csv.reader(f)
    hdr = next(r)
    return hdr, r

def build_rows():
    hdr, r = read_csv()
    # map header name -> list of column indexes (handles repeated columns)
    colidx = {}
    for i, c in enumerate(hdr):
        colidx.setdefault(c, []).append(i)
    def first(name):
        idxs = colidx.get(name)
        return idxs[0] if idxs else None
    label_cols = colidx.get("Labels", [])
    comp_cols = colidx.get("Components", [])
    rows = []
    for rowi, row in enumerate(r):
        def v(name):
            i = first(name)
            return row[i] if (i is not None and i < len(row)) else None
        # Labels: repeated -> list
        labels = [clean(row[i]) for i in label_cols if i < len(row) and clean(row[i])]
        comps = [clean(row[i]) for i in comp_cols if i < len(row) and clean(row[i])]
        r = {
            "T": clean(v("Issue Type")),
            "Project": clean(v("Project name")),
            "Key": clean(v("Issue key")),
            "IssueId": clean(v("Issue id")),
            "Summary": clean(v("Summary")),
            "Status": clean(v("Status")),
            "Priority": clean(v("Priority")),
            "Resolution": clean(v("Resolution")),
            "Created": to_utc_ts(v("Created")),
            "Updated": to_utc_ts(v("Updated")),
            "Resolved": to_utc_ts(v("Resolved")),
            "DueDate": parse_date(v("Due date")),
            "Reporter": clean(v("Reporter")),
            "ReporterId": clean(v("Reporter Id")),
            "Assignee": clean(v("Assignee")),
            "AssigneeId": clean(v("Assignee Id")),
            "Component": comps,
            "Description": clean(v("Description")),
            "SyncTime": SYNC_NOW,
            "IsDeleted": False,
            "DeletedAt": None,
        }
        if labels:
            r["Labels"] = labels
        rows.append(r)
    logging.info("Built %d ticket rows", len(rows))
    return rows

def main():
    dry = "--dryrun" in sys.argv
    if dry:
        rows = build_rows()
        print("total built:", len(rows))
        for r in rows[:5]:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    client = gcloud_auth.get_client(PROJECT)
    tbl_ref = f"{PROJECT}.{DATASET}.{TABLE}"
    rows = build_rows()
    # Idempotency: clear any existing IPCE rows, then insert fresh
    client.query(
        f"DELETE FROM `{tbl_ref}` WHERE Project = 'IP Customer Engineering'"
    ).result()
    logging.info("Cleared existing IPCE rows")
    import time as _t
    CH = 1500
    total = 0
    for i in range(0, len(rows), CH):
        batch = rows[i:i+CH]
        errs = None
        for attempt in range(5):
            errs = client.insert_rows_json(tbl_ref, batch)
            if not errs:
                break
            _t.sleep(3 * (attempt + 1))
        if errs:
            logging.error("insert errors batch %d: %s", i, errs[:5])
            print("INSERT ERRORS:", errs[:5]); return 1
        total += len(batch)
        logging.info("inserted batch, running total %d", total)
    logging.info("Inserted %d rows into target", total)
    print("DONE tickets rows:", len(rows))
    return 0

if __name__ == "__main__":
    sys.exit(main())
