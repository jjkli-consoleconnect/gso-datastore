import json, io, os, sys, requests
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
AUTH_B64 = open(os.path.join(DIR, "auth.txt")).read().strip()
BASE = "https://consoleconnect.atlassian.net/rest/api/3"

# ---- JSONL null counts for both files ----
for name in ["creator.jsonl", "creator_txce.jsonl"]:
    p = os.path.join(DIR, name)
    nulls = 0; total = 0
    if os.path.exists(p):
        with io.open(p, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln: continue
                total += 1
                rec = json.loads(ln)
                if rec.get("Creator") is None or str(rec.get("Creator","")).strip()=="":
                    nulls += 1
    print(f"{name}: total={total} null={nulls}")

# ---- BQ null counts ----
client = get_client("pccw-internal-virt-agent-uat")
TARGET = "pccw-internal-virt-agent-uat.GSO.JiraTickets"
q = f"""
SELECT Project, COUNT(*) AS total,
  SUM(CASE WHEN Creator IS NULL OR TRIM(Creator)='' THEN 1 ELSE 0 END) AS null_creator
FROM `{TARGET}`
GROUP BY Project
"""
print("\nBQ JiraTickets Creator stats by Project:")
for r in client.query(q).result():
    print(f"  {r.Project}: total={r.total} null_creator={r.null_creator}")

# ---- Empirical: chunked /search/jql with a 200-key chunk from the null region ----
keys = [f"TXCE-{i}" for i in range(1000, 1200)]
keys_jql = ", ".join(f'"{k}"' for k in keys)
resp = requests.get(BASE + "/search/jql", headers={"Authorization":"Basic "+AUTH_B64,
        "Accept":"application/json"},
        params={"jql": f"key in ({keys_jql})", "startAt":0, "maxResults":100, "fields":"key,creator"},
        timeout=60)
data = resp.json()
issues = data.get("issues", [])
nulls = sum(1 for it in issues if not (it.get("fields",{}) or {}).get("creator"))
print(f"\nChunk /search/jql 200 keys (1000-1199): status={resp.status_code} returned={len(issues)} total={data.get('total')} null_creator={nulls}")