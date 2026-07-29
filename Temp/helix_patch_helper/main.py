import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)


def patch_ticket(request):
    payload = request.get_json(silent=True) or {}
    ticket_id = payload.get('ticket_id', 'INC000006742385')

    client_id = os.environ.get('HELIX_CLIENT_ID')
    client_secret = os.environ.get('HELIX_CLIENT_SECRET')
    helix_host = os.environ.get('HELIX_HOST')

    if not all([client_id, client_secret, helix_host]):
        return jsonify({'error': 'missing env vars'}), 500

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
    token_resp.raise_for_status()
    token = token_resp.json()['access_token']

    headers = {
        'Authorization': f'Bearer {token}',
        'X-System-Id': 'jira',
        'Host': 'api.stage.corp.consoleconnect.com',
        'Content-Type': 'application/json',
    }

    url = f'https://{helix_host}/cs-helix-ticketing/internalHelix/troubleTicket/{ticket_id}'
    if helix_host.startswith('http://') or helix_host.startswith('https://'):
        url = f'{helix_host}/cs-helix-ticketing/internalHelix/troubleTicket/{ticket_id}'

    session = requests.Session()
    session.trust_env = False

    if payload.get('mode') == 'assign_group':
        patch_payload = {
            'id': ticket_id,
            '@type': 'troubleTicket',
            'assignedGroup': payload.get('assigned_group', 'PHSOC'),
        }
        r = session.patch(url, headers=headers, json=patch_payload, timeout=60, verify=False)
        return jsonify({'status_code': r.status_code, 'text': r.text[:4000]})

    if payload.get('mode') == 'read':
        r = session.get(url, headers=headers, timeout=60, verify=False)
        return jsonify({'status_code': r.status_code, 'text': r.text[:4000]})

    patch_payload = {
        'id': ticket_id,
        '@type': 'troubleTicket',
        'description': 'Change description',
        'relatedEntity': [],
        'notes': [],
        'statusChange': [],
    }

    r = session.patch(url, headers=headers, json=patch_payload, timeout=60, verify=False)
    return jsonify({'status_code': r.status_code, 'text': r.text[:4000]})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
