"""Fetch comments + changelogs for all IPCE issues from Jira API, write JSONL (resumable).
Matches the datapipe nightly row formats exactly.
"""
import json, os, sys, time, csv
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
AUTH_B64 = open(os.path.join(DIR, "auth.txt")).read().strip()
CSV = r"g:\My Drive\Scripts\Temp\IPCETicketComments.csv"
COUT = os.path.join(DIR, "comments.jsonl")
XOUT = os.path.join(DIR, "changelogs.jsonl")
DONE = os.path.join(DIR, "done.txt")
LOG = os.path.join(DIR, "fetch.log")
BASE = "https://consoleconnect.atlassian.net/rest/api/3"

SYNC_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")

def convert_ts(s):
    if not s:
        return None
    s = str(s)
    try:
        if s.endswith("Z"):
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M:%S")
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            if s.endswith("Z"):
                return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

def body_to_string(body):
    if body is None:
        return None
    if isinstance(body, str):
        return body
    try:
        if isinstance(body, dict) and "content" in body:
            parts = []
            def walk(node):
                if node is None:
                    return
                if isinstance(node, str):
                    parts.append(node); return
                if isinstance(node, dict):
                    if isinstance(node.get("text"), str):
                        parts.append(node["text"])
                    for k in ("content", "content_list"):
                        if isinstance(node.get(k), list):
                            for ch in node[k]:
                                walk(ch)
                    return
                if isinstance(node, list):
                    for it in node:
                        walk(it)
            walk(body.get("content"))
            if parts:
                return " ".join(parts)
    except Exception:
        pass
    try:
        return json.dumps(body, ensure_ascii=False)
    except Exception:
        return str(body)

def build_session():
    s = requests.Session()
    retry = Retry(total=6, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
    return s

def get_paged(session, path, params):
    """Return all items across pages for /comment or /changelog."""
    start = 0
    maxr = 100
    all_items = []
    while True:
        p = dict(params); p["startAt"] = start; p["maxResults"] = maxr
        url = BASE + path
        resp = session.get(url, params=p, headers={"Authorization": "Basic " + AUTH_B64, "Accept": "application/json"}, timeout=40)
        if resp.status_code in (401, 403):
            log(f"auth error {resp.status_code} on {url}"); raise RuntimeError("auth")
        resp.raise_for_status()
        data = resp.json()
        if path.endswith("/comment"):
            items = data.get("comments", [])
            total = data.get("total", len(all_items))
        else:
            items = data.get("values", [])
            total = data.get("total", len(all_items))
        all_items.extend(items)
        start += len(items)
        if start >= total or not items:
            break
        time.sleep(0.35)
    return all_items

def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    session = build_session()
    keys = []
    seen = set()
    with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f); next(r)
        for row in r:
            if row and row[1].strip():
                k = row[1].strip()
                if k not in seen:
                    seen.add(k); keys.append(k)
    done = set()

    if os.path.exists(DONE):
        with open(DONE, "r", encoding="utf-8") as f:
            done = {ln.strip() for ln in f if ln.strip()}
    todo = [k for k in keys if k not in done]
    if limit:
        todo = todo[:limit]
    log(f"total keys={len(keys)} done={len(done)} todo={len(todo)}")
    cc = xc = 0
    for n, key in enumerate(todo, 1):
        try:
            comments = get_paged(session, f"/issue/{key}/comment", {})
            for c in comments:
                a = c.get("author") or {}
                vis = c.get("visibility") or {}
                cc += 1
                with open(COUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "Issue_Key": key, "Comment_ID": c.get("id"),
                        "Author_Account_ID": a.get("accountId"),
                        "Author_Display_Name": a.get("displayName"),
                        "Created": convert_ts(c.get("created")),
                        "Updated": convert_ts(c.get("updated")),
                        "Body": body_to_string(c.get("body")),
                        "Visibility_Type": vis.get("type"),
                        "Visibility_Value": vis.get("value"),
                        "SyncTime": SYNC_NOW, "IsDeleted": False, "DeletedAt": None,
                    }, ensure_ascii=False) + "\n")
            histories = get_paged(session, f"/issue/{key}/changelog", {})
            for h in histories:
                a = h.get("author") or {}
                created_ts = convert_ts(h.get("created"))
                items = h.get("items", [])
                for idx, it in enumerate(items):
                    field = it.get("field")
                    xc += 1
                    with open(XOUT, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "Issue_Key": key, "History_ID": h.get("id"),
                            "Transition_Timestamp": created_ts,
                            "Changed_Field": field, "Changed_FieldType": it.get("fieldtype"),
                            "Change_Item_Index": idx,
                            "From_ID": (None if it.get("from") is None else str(it.get("from"))),
                            "From_Value": it.get("fromString"),
                            "To_ID": (None if it.get("to") is None else str(it.get("to"))),
                            "To_Value": it.get("toString"),
                            "Transitioned_From": it.get("fromString") if field == "status" else None,
                            "Transitioned_To": it.get("toString") if field == "status" else None,
                            "Transitioned_By_Account_ID": a.get("accountId"),
                            "Transitioned_By_Display_Name": a.get("displayName"),
                            "SyncTime": SYNC_NOW, "IsDeleted": False, "DeletedAt": None,
                        }, ensure_ascii=False) + "\n")
            with open(DONE, "a", encoding="utf-8") as f:
                f.write(key + "\n")
            time.sleep(0.35)
            if n % 25 == 0:
                log(f"progress {n}/{len(todo)} done; comments={cc} changelog_rows={xc}")
        except Exception as e:
            log(f"ERROR on {key}: {e}; pausing")
            time.sleep(20)
    log(f"COMPLETE todo={len(todo)} comments={cc} changelog_rows={xc}")
    print(f"DONE comments={cc} changelog_rows={xc}")

if __name__ == "__main__":
    main()

