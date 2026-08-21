"""Verify TXCE creator completeness: compare BQ vs live Jira API for the 5 still-null keys."""
import os, sys, requests, json
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
AUTH_B64 = open(os.path.join(DIR, "auth.txt")).read().strip()
PROJECT = "pccw-internal-virt-agent-uat"
TARGET = f"{PROJECT}.GSO.JiraTickets"

client = get_client(PROJECT)
# 1) Which TXCE keys still have null creator?
rows = list(client.query(
    f"SELECT DISTINCT Key, Creator FROM `{TARGET}` "
    f"WHERE Key LIKE 'TXCE-%' AND (Creator IS NULL OR TRIM(Creator)='') ORDER BY Key").result())
null_keys = [r.Key for r in rows]
print("BQ TXCE keys with NULL creator:", len(null_keys), null_keys)

# 2) Cross-check the CSV set: are all these ultimately from CSV?
import csv
csv_creator = {}
with open(r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv", "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        k = (r.get("Issue key") or "").strip()
        if k:
            c = (r.get("Creator") or "").strip()
            csv_creator[k] = c
print("\nOf those null keys, which are in CSV and what value does CSV give?")
for k in null_keys:
    print(f"  {k}: in_csv={k in csv_creator} csv_creator={csv_creator.get(k)!r}")

# 3) Live API check for these keys (hit /issue/{key} one by one)
print("\nLive Jira API checks:")
for k in null_keys:
    try:
        resp = requests.get(f"https://consoleconnect.atlassian.net/rest/api/3/issue/{k}",
                            headers={"Authorization":"Basic "+AUTH_B64, "Accept":"application/json"},
                            params={"fields":"key,creator"}, timeout=60)
        if resp.status_code == 200:
            fld = resp.json().get("fields", {}) or {}
            print(f"  {k}: HTTP {resp.status_code} creator={json.dumps(fld.get('creator'))}")
        else:
            print(f"  {k}: HTTP {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"  {k}: ERR {e}")