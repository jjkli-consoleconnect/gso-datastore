import json
import subprocess
import requests


def get_secret(secret_name: str) -> str:
    return subprocess.check_output([
        'gcloud', 'secrets', 'versions', 'access', 'latest',
        '--secret=' + secret_name,
        '--project=pccw-internal-virt-agent-uat',
    ], text=True).strip()

client_id = get_secret('jira-to-helix-uat-helix-auth0-client-id')
client_secret = get_secret('jira-to-helix-uat-helix-auth0-client-secret')
helix_host = get_secret('jira-to-helix-uat-host-name').strip()

token_resp = requests.post(
    'https://auth.stage.consoleconnect.com/oauth/token',
    data={
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'audience': 'api.stage.corp.consoleconnect.com',
    },
    timeout=30,
    verify=False,
)
print('TOKEN_STATUS', token_resp.status_code)
print(token_resp.text[:500])
token = token_resp.json()['access_token']

headers = {
    'Authorization': f'Bearer {token}',
    'X-System-Id': 'jira',
    'Host': 'api.stage.corp.consoleconnect.com',
    'Content-Type': 'application/json',
}

# use the internal host directly, with proxy bypass
session = requests.Session()
session.trust_env = False

url = f'https://{helix_host}/cs-helix-ticketing/internalHelix/troubleTicket/INC000006742385'
if helix_host.startswith('http://') or helix_host.startswith('https://'):
    url = f'{helix_host}/cs-helix-ticketing/internalHelix/troubleTicket/INC000006742385'

# First read the current ticket to see the relatedEntity shape.
print('GET_URL', url)
r = session.get(url, headers=headers, timeout=60, verify=False)
print('GET_STATUS', r.status_code)
print(r.text[:4000])

# Build a patch payload that preserves the customer relation and removes the SR relation.
# If the API only accepts a full object, this is the safest shape.
payload = {
    'id': 'INC000006742385',
    'description': 'Change description',
    '@type': 'troubleTicket',
    'relatedEntity': [],
    'notes': [],
    'statusChange': [],
}

print('PATCH_PAYLOAD', json.dumps(payload, indent=2))
r2 = session.patch(url, headers=headers, json=payload, timeout=60, verify=False)
print('PATCH_STATUS', r2.status_code)
print(r2.text[:4000])
