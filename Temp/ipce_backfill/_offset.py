import csv, sys, datetime
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"
PROJECT = "pccw-internal-virt-agent-uat"
TARGET = f"{PROJECT}.GSO.JiraTickets"

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}

def parse_dt(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = s.split()
        mon = MONTHS[parts[0]]
        day = int(parts[1].rstrip(","))
        yr = int(parts[2])
        hm = parts[3].split(":")
        hr, mi = int(hm[0]), int(hm[1])
        return datetime.datetime(yr, mon, day, hr, mi)
    except Exception as e:
        print("parse fail:", repr(s), e)
        return None

csv_created = {}
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        k = (r.get("Issue key") or "").strip()
        if k:
            csv_created[k] = parse_dt(r.get("Created"))

client = get_client(PROJECT)
sample = list(csv_created)[:40]
rows = list(client.query(f"SELECT Key, Created FROM `{TARGET}` WHERE Key IN UNNEST(@k)",
    job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("k", "STRING", sample)])).result())
bq_created = {r.Key: r.Created for r in rows}
print("key | CSV(local) | BQ(utc) | offset_hours")
for k in sample:
    c = csv_created[k]; b = bq_created.get(k)
    if not c or b is None:
        continue
    b_naive = b.replace(tzinfo=None)
    off = (c - b_naive).total_seconds()/3600
    print(f"{k} | {c} | {b.isoformat()} | {off}")