import json, subprocess, urllib.request

pairs = [
    ("pccw-internal-virt-agent-uat", r"BigQuery/pccw-internal-virt-agent-uat/wanda_ds/views/TicketMaster.sql"),
    ("pccw-internal-virtual-agent", r"BigQuery/pccw-internal-virtual-agent/wanda_ds/views/TicketMaster.sql"),
]
token = subprocess.check_output(["gcloud.cmd", "auth", "print-access-token"], text=True).strip()
for proj, path in pairs:
    with open(path, encoding="utf-8-sig") as f:
        sql = f.read()
    body = json.dumps({"view": {"query": sql, "useLegacySql": False}}).encode()
    req = urllib.request.Request(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{proj}/datasets/wanda_ds/tables/TicketMaster",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            print("updated", proj, r.status)
    except Exception as e:
        print("FAILED", proj, e)
