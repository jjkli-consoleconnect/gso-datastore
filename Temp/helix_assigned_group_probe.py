import json
import subprocess
from urllib.parse import urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT = "pccw-internal-virt-agent-uat"
TICKET_ID = "INC000006742351"
GCLOUD = r"C:\Users\jjkli\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"


def secret(name: str) -> str:
    return subprocess.check_output(
        [
            GCLOUD,
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={name}",
            f"--project={PROJECT}",
        ],
        text=True,
    ).strip()


client_id = secret("jira-to-helix-uat-helix-auth0-client-id")
client_secret = secret("jira-to-helix-uat-helix-auth0-client-secret")
helix_host = secret("jira-to-helix-uat-host-name")
parsed = urlparse(helix_host if "://" in helix_host else f"https://{helix_host}")
host = parsed.netloc or parsed.path

token_resp = requests.post(
    "https://auth.stage.consoleconnect.com/oauth/token",
    data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": "api.stage.corp.consoleconnect.com",
    },
    timeout=20,
)
token_resp.raise_for_status()
token = token_resp.json()["access_token"]
headers = {
    "Authorization": f"Bearer {token}",
    "X-System-Id": "jira",
    "Host": "api.stage.corp.consoleconnect.com",
    "Content-Type": "application/json",
}
url = f"https://{host}/cs-helix-ticketing/internalHelix/troubleTicket/{TICKET_ID}"

for action, payload in [
    ("get", None),
    ("patch", {"@type": "troubleTicket", "assignedGroup": "ASOC"}),
    ("get_after", None),
]:
    if action.startswith("get"):
        resp = requests.get(url, headers=headers, timeout=30, verify=False)
    else:
        resp = requests.patch(url, headers=headers, json=payload, timeout=30, verify=False)
    print(f"=== {action} status={resp.status_code} ===")
    print(resp.text[:4000])
