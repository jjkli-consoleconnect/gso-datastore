import json, urllib.request

AUTH = open(r"g:\My Drive\Scripts\Temp\ipce_backfill\auth.txt").read().strip()
BASE = "https://consoleconnect.atlassian.net/rest/api/3"

def get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(url, headers={"Authorization": "Basic " + AUTH, "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())

import urllib.parse

# Comments
c = get("/issue/IPCE-17596/comment", {"maxResults": 5})
print("COMMENTS total:", c.get("total"))
for cm in c.get("comments", [])[:3]:
    a = cm.get("author") or {}
    print("  id:", cm.get("id"), "| author:", a.get("accountId"), "| display:", a.get("displayName"), "| created:", cm.get("created"), "| body:", json.dumps(cm.get("body"))[:120])

# Changelog
try:
    cl = get("/issue/IPCE-17596/changelog", {"maxResults": 3})
    print("CHANGELOG total:", cl.get("total"))
    for h in cl.get("values", [])[:3]:
        a = h.get("author") or {}
        print("  hist id:", h.get("id"), "| created:", h.get("created"), "| author:", a.get("accountId"), "| items:", json.dumps(h.get("items"))[:200])
except Exception as e:
    print("changelog error:", e)
