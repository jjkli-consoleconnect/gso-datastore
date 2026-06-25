#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.secrets_manager import load_jira_credentials


def count_for(jql: str, session: requests.Session, base_url: str) -> int:
    resp = session.get(
        f"{base_url}/rest/api/3/search/jql",
        params={"jql": jql, "maxResults": 0, "fields": "key"},
        timeout=60,
    )
    resp.raise_for_status()
    return int(resp.json().get("total", 0))


def main() -> int:
    token, user = load_jira_credentials(os.environ.get("GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat"))
    if not token or not user:
        print("Failed to load jira creds")
        return 2

    session = requests.Session()
    session.auth = (user, token)
    session.headers.update({"Accept": "application/json"})
    base_url = "https://consoleconnect.atlassian.net"

    looker = count_for('project in (CCAI,GDA,GKC,GTA) AND component = "Looker Studio"', session, base_url)
    data_studio = count_for('project in (CCAI,GDA,GKC,GTA) AND component = "Data Studio"', session, base_url)

    print(f"Looker Studio: {looker}")
    print(f"Data Studio: {data_studio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
