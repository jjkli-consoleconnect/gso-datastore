import json, subprocess

name = "projects/14417857267/locations/europe/transferConfigs/6a33091c-0000-27ff-8aa4-001a114ce186"
url = f"https://bigquerydatatransfer.googleapis.com/v1/{name}?updateMask=params,schedule"

with open(r"c:\dev\consoleconnect\Temp\shrpeople_counts_params.json") as f:
    query = json.load(f)["query"]

token = subprocess.check_output(
    [r"C:\Users\jjkli\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
     "auth", "print-access-token"], text=True
).strip()

body = {
    "params": {"query": query},
    "schedule": "every day 00:00",
}

import urllib.request
req = urllib.request.Request(
    url,
    data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="PATCH",
)
with urllib.request.urlopen(req) as resp:
    print(resp.status, resp.read().decode()[:200])
