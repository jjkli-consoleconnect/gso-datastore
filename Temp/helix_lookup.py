import os
import requests

client_id = os.popen("gcloud secrets versions access latest --secret='jira-to-helix-uat-helix-auth0-client-id' --project='pccw-internal-virt-agent-uat'").read().strip()
client_secret = os.popen("gcloud secrets versions access latest --secret='jira-to-helix-uat-helix-auth0-client-secret' --project='pccw-internal-virt-agent-uat'").read().strip()
helix_host = os.popen("gcloud secrets versions access latest --secret='jira-to-helix-uat-host-name' --project='pccw-internal-virt-agent-uat'").read().strip()

token_resp = requests.post(
    'https://auth.stage.consoleconnect.com/oauth/token',
    data={
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'audience': 'api.stage.corp.consoleconnect.com',
    },
    timeout=20,
    verify=False,
)
token_resp.raise_for_status()
token = token_resp.json()['access_token']

host_value = helix_host if not helix_host.startswith('http') else helix_host.split('//', 1)[1]
url = f'https://{host_value}/cs-helix-ticketing/internalHelix/troubleTicket/INC000006742383'
headers = {'Authorization': f'Bearer {token}', 'X-System-Id': 'jira', 'Host': 'api.stage.corp.consoleconnect.com'}
resp = requests.get(url, headers=headers, timeout=30, verify=False)
print('STATUS', resp.status_code)
print(resp.text[:4000])
