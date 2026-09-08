import json
import subprocess
import urllib.request

with open(r"BigQuery/pccw-internal-virt-agent-uat/GSOEDPLink/views/CostItem.sql", "r", encoding="utf-8") as f:
    sql = f.read()

import shutil
GCLOUD = shutil.which("gcloud") or shutil.which("gcloud.cmd")
token = subprocess.check_output(
    [GCLOUD, "auth", "print-access-token"], text=True
).strip()

url = "https://bigquery.googleapis.com/bigquery/v2/projects/pccw-internal-virt-agent-uat/datasets/GSOEDPLink/tables/CostItem"
body = json.dumps({"view": {"query": sql, "useLegacySql": False}}).encode()
req = urllib.request.Request(url, data=body, method="PATCH", headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
})
with urllib.request.urlopen(req) as resp:
    print("STATUS", resp.status)
print("VIEW UPDATED")

