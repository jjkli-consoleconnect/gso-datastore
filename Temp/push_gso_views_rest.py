import json, subprocess, urllib.request

views = [
    ("pccw-internal-virt-agent-uat", "GSO", "HDWL", r"BigQuery/pccw-internal-virt-agent-uat/GSO/views/HDWL.sql"),
    ("pccw-internal-virt-agent-uat", "GSO", "JIRA_HD", r"BigQuery/pccw-internal-virt-agent-uat/GSO/views/JIRA_HD.sql"),
]
token = subprocess.check_output(["gcloud.cmd", "auth", "print-access-token"], text=True).strip()
for proj, ds, table, path in views:
    with open(path, encoding="utf-8-sig") as f:
        sql = f.read()
    body = json.dumps({"view": {"query": sql, "useLegacySql": False}}).encode()
    req = urllib.request.Request(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{proj}/datasets/{ds}/tables/{table}",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            print("updated", f"{proj}.{ds}.{table}", r.status)
    except Exception as e:
        print("FAILED", f"{proj}.{ds}.{table}", e)
