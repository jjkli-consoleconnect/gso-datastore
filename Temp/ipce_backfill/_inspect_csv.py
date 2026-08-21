import csv, sys, os
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp"
CSV = os.path.join(DIR, "TXCEAllTickets.csv")

unique_keys = {}
null_creator = 0
empty_key = 0
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    headers = list(reader.fieldnames or [])
    rows = list(reader)

print("=== header columns ===")
for i, h in enumerate(headers, 1):
    print(f"  {i}: {h!r}")

print("\n=== row count (data):", len(rows))

for r in rows:
    k = (r.get("Issue key") or "").strip()
    if not k:
        empty_key += 1
        continue
    c = (r.get("Creator") or "").strip()
    if not c:
        null_creator += 1
    unique_keys[k] = unique_keys.get(k, 0) + 1

print("empty key rows:", empty_key)
print("rows with empty Creator:", null_creator)
dups = {k: v for k, v in unique_keys.items() if v > 1}
print("duplicate keys:", len(dups), "->", list(dups.items())[:5])

targets = ["TXCE-7131","TXCE-7132","TXCE-7133","TXCE-7149","TXCE-7155",
           "TXCE-7156","TXCE-7186","TXCE-7188","TXCE-7198"]
print("\n=== complaint keys in CSV ===")
for t in targets:
    print(f"  {t}: in_csv={t in unique_keys} creator={next((r['Creator'] for r in rows if (r.get('Issue key') or '').strip()==t), None)}")

# BQ schema
client = get_client("pccw-internal-virt-agent-uat")
print("\n=== BQ JiraTickets schema ===")
for sf in client.get_table("pccw-internal-virt-agent-uat.GSO.JiraTickets").schema:
    print(f"  {sf.name} ({sf.field_type}, mode={sf.mode})")