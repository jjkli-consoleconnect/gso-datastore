import json, os, sys, time, requests
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
AUTH_B64 = open(os.path.join(DIR, "auth.txt")).read().strip()
BASE = "https://consoleconnect.atlassian.net/rest/api/3"

keys = ["TXCE-7131","TXCE-7132","TXCE-7133","TXCE-7149","TXCE-7155",
        "TXCE-7156","TXCE-7186","TXCE-7188","TXCE-7198"]
keys_jql = ", ".join(f'"{k}"' for k in keys)
jql = f"key in ({keys_jql})"

def api_get(url, params):
    return requests.get(BASE + url, headers={"Authorization":"Basic "+AUTH_B64,
                        "Accept":"application/json"}, params=params, timeout=60)

for url in ["/search/jql", "/search"]:
    resp = api_get(url, {"jql": jql, "startAt": 0, "maxResults": 100, "fields": "key,creator"})
    print(f"\n>>> {url} status={resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:500])
        continue
    data = resp.json()
    issues = data.get("issues", [])
    print(f"   returned {len(issues)} issues of total={data.get('total')}")
    for it in issues[:9]:
        fld = it.get("fields", {}) or {}
        print(f"   {it.get('key')}: creator={json.dumps(fld.get('creator'))}")

print("\n=== individual issue fetches ===")
for k in keys[:3]:
    resp = api_get("/issue/"+k, {"fields": "key,creator"})
    print(f"\n>>> /issue/{k} status={resp.status_code}")
    if resp.status_code == 200:
        fld = resp.json().get("fields", {}) or {}
        print(f"   {resp.json().get('key')}: creator={json.dumps(fld.get('creator'))}")