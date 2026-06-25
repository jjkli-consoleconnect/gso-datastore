#!/usr/bin/env python3
"""Revert Looker Studio component naming back to Data Studio for AA projects."""

from __future__ import annotations

import logging
import os
import sys
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.secrets_manager import load_jira_credentials


def fetch_issues(session: requests.Session, base_url: str) -> list[dict]:
    jql = 'project in (CCAI,GDA,GKC,GTA) AND component = "Looker Studio"'
    start_at = 0
    max_results = 100
    all_issues: list[dict] = []

    while True:
        resp = session.get(
            f"{base_url}/rest/api/3/search/jql",
            params={
                "jql": jql,
                "fields": "components",
                "startAt": start_at,
                "maxResults": max_results,
            },
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        issues = payload.get("issues", [])
        all_issues.extend(issues)
        if len(issues) < max_results:
            break
        start_at += max_results

    return all_issues


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token, user = load_jira_credentials(os.environ.get("GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat"))
    if not token or not user:
        logging.error("Could not load Jira credentials")
        return 2

    session = requests.Session()
    session.auth = (user, token)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    base_url = "https://consoleconnect.atlassian.net"

    issues = fetch_issues(session, base_url)
    logging.info("Found %s issues with Looker Studio component", len(issues))

    changed = 0
    failed = 0

    for issue in issues:
        key = issue["key"]
        comps = issue.get("fields", {}).get("components") or []
        old_names = [c.get("name", "").strip() for c in comps if c.get("name")]

        new_names: list[str] = []
        seen: set[str] = set()
        for name in old_names:
            mapped = "Data Studio" if name in ("Looker Studio", "LookerStudio") else name
            if mapped not in seen:
                new_names.append(mapped)
                seen.add(mapped)

        if old_names == new_names:
            continue

        payload = {"fields": {"components": [{"name": n} for n in new_names]}}
        try:
            resp = session.put(f"{base_url}/rest/api/3/issue/{key}", json=payload, timeout=60)
            resp.raise_for_status()
            changed += 1
            logging.info("%s: %s -> %s", key, old_names, new_names)
        except Exception as exc:
            failed += 1
            logging.error("Failed for %s: %s", key, exc)
        time.sleep(0.2)

    logging.info("Revert complete changed=%s failed=%s", changed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
