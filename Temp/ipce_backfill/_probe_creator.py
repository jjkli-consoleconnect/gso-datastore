import json, io, os, sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
JSONL = os.path.join(DIR, "creator_txce.jsonl")

targets = ["TXCE-7131","TXCE-7132","TXCE-7133","TXCE-7149","TXCE-7155",
           "TXCE-7156","TXCE-7186","TXCE-7188","TXCE-7198"]

# 1) Load JSONL map
map_by_key = {}
null_created = 0
with io.open(JSONL, "r", encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln: continue
        rec = json.loads(ln)
        map_by_key[rec.get("Key")] = rec.get("Creator")
        if rec.get("Creator") is None and rec.get("Key","").startswith("TXCE-"):
            null_created += 1

print(f"JSONL total lines: {len(map_by_key)} | TXCE null creators in JSONL: {null_created}")
print(f"JSONL contains target keys?")
for k in targets:
    print(f"   {k}: in_jsonl={k in map_by_key} creator_in_jsonl={map_by_key.get(k)}")

# 2) BQ current state for these keys
client = get_client("pccw-internal-virt-agent-uat")
TARGET = "pccw-internal-virt-agent-uat.GSO.JiraTickets"
q = f"""
SELECT Key, Creator
FROM `{TARGET}`
WHERE Key IN UNNEST(@keys)
ORDER BY Key
"""
rows = list(client.query(q, job_config=bigquery.QueryJobConfig(
    query_parameters=[bigquery.ArrayQueryParameter("keys", "STRING", targets)]
)).result())
print("\nBQ current state (Key, Creator):")
for r in rows:
    print(f"  {r.Key}: creator={r.Creator!r}")

# 3) count null creators in TXCE in BQ
q2 = f"""
SELECT COUNT(*) AS total,
  SUM(CASE WHEN Creator IS NULL OR TRIM(Creator)='' THEN 1 ELSE 0 END) AS null_creator
FROM `{TARGET}`
WHERE Project = @proj AND Key LIKE 'TXCE-%'
"""
r2 = list(client.query(q2, job_config=bigquery.QueryJobConfig(
    query_parameters=[bigquery.ScalarQueryParameter("proj", "STRING", "Transmission TX-CE")])
).result())
print("\nBQ TXCE Creator stats:")
for row in r2:
    print(f"  total={row.total} null_creator={row.null_creator}")