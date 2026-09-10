"""Try minimal canonical ROW ACCESS POLICY DDL to diagnose the parser."""
import json, shutil, subprocess, urllib.request, urllib.error

SQL = """CREATE ROW ACCESS POLICY `pccw-internal-virt-agent-uat.Mirror.edp_sr_rla`
GRANT TO ("user:ken.mk.tam@consoleconnect.com")
FILTER USING (TRUE);"""

token = subprocess.check_output(
    [shutil.which("gcloud") or shutil.which("gcloud.cmd"), "auth", "print-access-token"], text=True
).strip()

url = "https://bigquery.googleapis.com/bigquery/v2/projects/pccw-internal-virt-agent-uat/queries"
data = json.dumps({"query": SQL, "useLegacySql": False}).encode()
req = urllib.request.Request(
    url, data=data, method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        print("STATUS", r.status)
        print(r.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP ERROR", e.code)
    print(e.read().decode())