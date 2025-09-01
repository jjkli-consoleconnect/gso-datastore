import json
import requests
import os
import sys

CONFIG_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config.json'))

def mask(s):
    if not s:
        return None
    return s[:3] + '...' + s[-3:]


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        # Try alternate locations (repo root), then fail
        alt = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config.json'))
        if alt != CONFIG_PATH:
            try:
                with open(alt) as f:
                    return json.load(f)
            except Exception:
                pass
        print(f"ERROR: cannot load config.json at {CONFIG_PATH}: {e}")
        sys.exit(2)


def do_request(session, method, url, **kwargs):
    try:
        resp = session.request(method, url, timeout=30, **kwargs)
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:1000]
        return status, body
    except requests.RequestException as e:
        return None, str(e)


if __name__ == '__main__':
    cfg = load_config()
    # Credential lookup order: config jira_user -> env JIRA_USER -> other config keys -> default
    jira_user = cfg.get('jira_user') or os.environ.get('JIRA_USER') or cfg.get('jira_email') or cfg.get('jira_username')
    token = cfg.get('jira_api_token')
    if not token:
        print('ERROR: jira_api_token not found in config.json')
        sys.exit(3)

    if not jira_user:
        # Not ideal, but fall back to the original default used previously in the script
        jira_user = 'jjkli@consoleconnect.com'
        print('WARNING: jira_user not found in config.json or JIRA_USER env; falling back to', jira_user)
    else:
        print('Using jira_user:', jira_user)
    print('Using jira_api_token (masked):', mask(token))

    session = requests.Session()
    session.auth = (jira_user, token)
    session.headers.update({'Accept': 'application/json'})

    base = 'https://consoleconnect.atlassian.net'
    endpoints = [
        ('GET', base + '/rest/api/3/myself'),
        ('GET', base + '/rest/api/3/project'),
        ('POST', base + '/rest/api/3/search')
    ]

    # For search, use a minimal JQL that previously failed; keep it safe
    search_payload = {"jql": 'project = "Console Application Support"', "startAt": 0, "maxResults": 1}

    results = {}
    for method, url in endpoints:
        print('\n->', method, url)
        if url.endswith('/search'):
            status, body = do_request(session, method, url, json=search_payload)
        else:
            status, body = do_request(session, method, url)
        print('Status:', status)
        if isinstance(body, dict):
            # Print keys and any errorMessages / size
            keys = list(body.keys())
            print('Body keys:', keys[:20])
            if 'errorMessages' in body:
                print('errorMessages:', body.get('errorMessages'))
            if 'warningMessages' in body and body.get('warningMessages'):
                print('warningMessages:', body.get('warningMessages'))
            if 'length' in body:
                print('length:', body.get('length'))
        else:
            s = str(body)
            print('Body (text, truncated):', s[:1000])

    print('\nDone')
