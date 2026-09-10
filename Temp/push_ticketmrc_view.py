"""Push the updated Restricted.TicketMRC view definition to BigQuery."""
import json
import shutil
import subprocess
import urllib.request

SQL_PATH = r"BigQuery/pccw-internal-virt-agent-uat/Restricted/views/TicketMRC.sql"
URL = (
    "https://bigquery.googleapis.com/bigquery/v2/projects/"
    "pccw-internal-virt-agent-uat/datasets/Restricted/tables/TicketMRC"
)

with open(SQL_PATH, "r", encoding="utf-8") as f:
    sql = f.read()

GCLOUD = shutil.which("gcloud") or shutil.which("gcloud.cmd")
token = subprocess.check_output([GCLOUD, "auth", "print-access-token"], text=True).strip()

body = json.dumps({"view": {"query": sql, "useLegacySql": False}}).encode()
req = urllib.request.Request(
    URL, data=body, method="PATCH",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as resp:
        print("STATUS", resp.status)
    print("VIEW UPDATED")
except urllib.error.HTTPError as e:
    print("HTTP ERROR", e.code)
    print(e.read().decode())

