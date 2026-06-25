#!/usr/bin/env python3
"""Bulk-clean Jira components for AA projects using Secret Manager credentials."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

import requests

# Ensure repo root imports work when run from Temp/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.secrets_manager import load_jira_credentials


PROJECTS = ("CCAI", "GDA", "GKC", "GTA")
MAPPING = {
    "Data Studio": "Looker Studio",
    "LookerStudio": "Looker Studio",
    "EventTriggered": "Event Triggered",
    "New Function": "New Feature",
}


def fetch_issues(session: requests.Session, base_url: str, jql: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    start_at = 0
    max_results = 100

    while True:
        params = {
            "jql": jql,
            "fields": "components",
            "startAt": start_at,
            "maxResults": max_results,
        }
        resp = session.get(f"{base_url}/rest/api/3/search/jql", params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()

        batch = payload.get("issues", [])
        issues.extend(batch)

        if len(batch) < max_results:
            break
        start_at += max_results

    return issues


def transform_components(components: list[dict[str, Any]]) -> tuple[list[str], list[str], bool]:
    old_names = [c.get("name", "").strip() for c in components if c.get("name")]

    seen: set[str] = set()
    new_names: list[str] = []
    changed = False

    for name in old_names:
        mapped = MAPPING.get(name, name)
        if mapped != name:
            changed = True
        if mapped not in seen:
            seen.add(mapped)
            new_names.append(mapped)

    if old_names != new_names:
        changed = True

    return old_names, new_names, changed


def update_issue_components(session: requests.Session, base_url: str, issue_key: str, new_names: list[str]) -> None:
    payload = {"fields": {"components": [{"name": n} for n in new_names]}}
    resp = session.put(f"{base_url}/rest/api/3/issue/{issue_key}", json=payload, timeout=60)
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean Jira components for AA projects.")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Default is dry-run.")
    parser.add_argument("--project-id", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "pccw-internal-virt-agent-uat"))
    parser.add_argument("--site", default="https://consoleconnect.atlassian.net")
    parser.add_argument("--pause-sec", type=float, default=0.2)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token, user = load_jira_credentials(args.project_id)
    if not token or not user:
        logging.error("Could not load Jira credentials from Secret Manager.")
        return 2

    # Restrict to AA projects and only component values that need cleanup.
    targets = ",".join(f'\"{k}\"' for k in MAPPING.keys())
    projects = ",".join(PROJECTS)
    jql = f"project in ({projects}) AND component in ({targets})"

    session = requests.Session()
    session.auth = (user, token)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    logging.info("Fetching issues with cleanup-target components...")
    issues = fetch_issues(session, args.site, jql)
    logging.info("Found %s issues matching target cleanup components.", len(issues))

    changed_count = 0
    applied_count = 0
    failed_count = 0

    for issue in issues:
        key = issue.get("key")
        fields = issue.get("fields", {})
        components = fields.get("components") or []

        old_names, new_names, changed = transform_components(components)
        if not changed:
            continue

        changed_count += 1
        logging.info("%s: %s -> %s", key, old_names, new_names)

        if args.apply:
            try:
                update_issue_components(session, args.site, key, new_names)
                applied_count += 1
            except Exception as exc:
                failed_count += 1
                logging.error("Failed update for %s: %s", key, exc)
            time.sleep(args.pause_sec)

    mode = "APPLY" if args.apply else "DRY-RUN"
    logging.info("Mode=%s changed=%s applied=%s failed=%s", mode, changed_count, applied_count, failed_count)

    if failed_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
