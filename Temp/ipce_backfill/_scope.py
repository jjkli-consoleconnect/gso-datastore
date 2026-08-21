import csv, os, sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"
PROJECT = "pccw-internal-virt-agent-uat"
TARGET = f"{PROJECT}.GSO.JiraTickets"

csv_keys = set()
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        k = (r.get("Issue key") or "").strip()
        if k:
            csv_keys.add(k)
print("CSV unique keys:", len(csv_keys))

client = get_client(PROJECT)
# ALL BQ rows where Key starts with TXCE- (regardless of Project column)
bq_txce = {row.Key for row in client.query(
    f"SELECT DISTINCT Key FROM `{TARGET}` WHERE Key LIKE 'TXCE-%'").result()}
print("BQ TXCE-prefixed keys:", len(bq_txce))

in_csv_not_bq = sorted(csv_keys - bq_txce)
in_bq_not_csv = sorted(bq_txce - csv_keys)
print("CSV keys NOT in BQ (candidates to insert):", len(in_csv_not_bq))
print("BQ keys not in CSV:", len(in_bq_not_csv), in_bq_not_csv[:10])

# Check the 5 null creators from earlier + their Project/Deleted flags
probe = sorted(set(["TXCE-6843","TXCE-6872","TXCE-6874","TXCE-7127","TXCE-7128"]) & bq_txce)
if probe:
    rows = list(client.query(
        f"SELECT Key, Project, Creator, IsDeleted FROM `{TARGET}` WHERE Key IN UNNEST(@k) ORDER BY Key",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("k", "STRING", probe)])).result())
    print("\n5 orphan BQ rows (Key, Project, Creator, IsDeleted):")
    for x in rows:
        print(f"  {x.Key}: project={x.Project!r} creator={x.Creator!r} deleted={x.IsDeleted}")