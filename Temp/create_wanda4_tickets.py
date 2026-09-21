"""Create Wanda 4.0 CCAI backlog tickets from Temp/wanda4.md via Jira REST API v3.

Hierarchy:
  CCAI-360 (existing Wanda 4.0 Task, unchanged)
    -> 5 new parent Tasks, each issue-linked to CCAI-360 ("Relates")
         -> 21 Sub-tasks

Usage:
  python Temp/create_wanda4_tickets.py            # dry run, prints payloads
  python Temp/create_wanda4_tickets.py --execute  # real creation
"""

import html
import json
import re
import sys
import time
import subprocess
from pathlib import Path

import requests

MD_PATH = Path(__file__).resolve().parent / "wanda4.md"
JIRA_BASE = "https://consoleconnect.atlassian.net"
PROJECT_KEY = "CCAI"
PARENT_TICKET = "CCAI-360"  # existing Wanda 4.0 ticket
LINK_TYPE_NAME = "Relates"

ISSUE_TYPE_TASK = "Task"
ISSUE_TYPE_SUBTASK = "Sub-task"

# Resolved via /rest/api/3/user/search on 2026-09-21
ACCOUNT_IDS = {
    "Paulo Gabriel Bertol": "712020:8f056461-7ad1-47c3-8011-a0ae4dc1dc8c",
    "Jann Rayco": "712020:016b292b-efdf-4c3d-bb6c-cd9829d6a0fa",
    "Jens Li": "712020:0b55fcfe-0bec-44a5-b34a-2bf2e61d8a9d",
    "Sheldon": "712020:f2591239-b215-47d1-8951-6b01e716e441",
    "Ken Tam": "5cb6dc239eec1011988bcbec",
}


def get_auth():
    def secret(name):
        for exe in ("gcloud.cmd", "gcloud", "gcloud.ps1"):
            try:
                cmd = (
                    f"{exe} secrets versions access latest "
                    f"--secret={name} --project=pccw-internal-virtual-agent"
                )
                out = subprocess.run(
                    cmd,
                    capture_output=True, text=True, check=True,
                    shell=True,
                ).stdout.strip()
                if out:
                    return out
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        raise RuntimeError(f"Could not read secret {name} via gcloud")

    return (secret("jira-user-email"), secret("jira-api-token"))


# ---------------- md parsing ----------------

FIELD_RE = re.compile(r"^\s*\*\s+\*\*(.+?)\*\*\s*:\s*(.*)$")


def parse_md(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    tickets = []
    current = None
    mode = None  # None | "description" | "ac"

    for raw in lines:
        line = raw.rstrip()
        head_p = re.match(r"^##\s+PARENT TICKET\s+(\d+)\s*:\s*(.+)$", line)
        head_c = re.match(r"^###\s+Child Ticket\s+([\d.]+)\s*:\s*(.+)$", line)

        if head_p or head_c:
            if current:
                tickets.append(current)
            current = {"fields": {}, "desc_lines": [], "ac_lines": []}
            mode = None
            continue

        if current is None:
            continue

        if line.strip() == "---":
            continue

        if line.strip() == "**Acceptance Criteria:**":
            mode = "ac"
            continue

        m = FIELD_RE.match(line)
        if m:
            key = m.group(1).strip().lower()
            mode = "description" if key == "description" else "field"
            value = html.unescape(m.group(2).strip())
            current["fields"][key] = value
            if key == "description" and value:
                # Seed desc_lines so single-line descriptions are not lost.
                current["desc_lines"].append(value)
            continue

        if mode in ("description", "ac") and line.strip():
            current["desc_lines" if mode == "description" else "ac_lines"].append(
                html.unescape(line.strip())
            )

    if current:
        tickets.append(current)
    return tickets


def adf_paragraph(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def build_description_adf(ticket):
    content = [adf_paragraph(clean_md_line(ln)) for ln in ticket["desc_lines"] if ln.strip()]
    content = [c for c in content if c["content"]]
    if ticket["ac_lines"]:
        content.append({
            "type": "heading", "attrs": {"level": 3},
            "content": [{"type": "text", "text": "Acceptance Criteria"}],
        })
        for ln in ticket["ac_lines"]:
            text = clean_md_line(ln)
            if not text:
                continue
            content.append({
                "type": "bulletList",
                "content": [{"type": "listItem", "content": [adf_paragraph(text)]}],
            })
    return {"type": "doc", "version": 1, "content": content}


def resolve_assignee(raw):
    """Return (account_id or None, note) for the spec assignee string."""
    names = [p.strip() for p in raw.split("/") if p.strip()] if raw else []
    if not names:
        return None, ""
    note = f"Assignment team: {', '.join(names)}" if len(names) > 1 else ""
    first = names[0]
    if first not in ACCOUNT_IDS:
        raise KeyError(f"Unknown assignee: {first!r} (raw={raw!r})")
    return ACCOUNT_IDS[first], note


def build_payload(ticket, parent_key=None):
    f = ticket["fields"]
    fake_key = f["jira key"].strip("`")
    assignee_raw = f.get("assignee", "")
    reporter_raw = f.get("reporter", "")

    assignee_id, note = resolve_assignee(assignee_raw)
    desc_lines = list(ticket["desc_lines"])
    if note:
        desc_lines.append(note)
    desc = build_description_adf({**ticket, "desc_lines": desc_lines})

    fields = {
        "project": {"key": PROJECT_KEY},
        "summary": f["summary"],
        "description": desc,
        "priority": {"name": f.get("priority", "Medium")},
    }
    if assignee_id:
        fields["assignee"] = {"id": assignee_id}
    if parent_key:
        fields["issuetype"] = {"id": "10169"}  # Sub-task (id avoids name-lookup 400)
        fields["parent"] = {"key": parent_key}
    else:
        fields["issuetype"] = {"name": ISSUE_TYPE_TASK}
        if reporter_raw in ACCOUNT_IDS:
            fields["reporter"] = {"id": ACCOUNT_IDS[reporter_raw]}

    return fake_key, {"fields": fields}


# ---------------- Jira calls ----------------

def create_issue(auth, payload):
    r = requests.post(
        f"{JIRA_BASE}/rest/api/3/issue", auth=auth, json=payload, timeout=30
    )
    if r.status_code != 201:
        raise RuntimeError(f"create_issue {r.status_code}: {r.text[:500]}")
    return r.json()["key"]


def get_issue_id(auth, key):
    r = requests.get(
        f"{JIRA_BASE}/rest/api/3/issue/{key}", auth=auth,
        params={"fields": "id"}, timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"get_issue {r.status_code}: {r.text[:300]}")
    return r.json()["id"]


def create_subtask_with_retry(auth, payload, parent_key, attempts=12, delay=5):
    """Create subtask; parent must be referenced by id and Jira index may lag."""
    last = None
    for i in range(attempts):
        parent_id = get_issue_id(auth, parent_key)
        payload["fields"]["parent"] = {"id": parent_id}
        r = requests.post(
            f"{JIRA_BASE}/rest/api/3/issue", auth=auth, json=payload, timeout=30
        )
        if r.status_code == 201:
            return r.json()["key"]
        last = RuntimeError(f"create_issue {r.status_code}: {r.text[:500]}")
        print(f"    attempt {i + 1}/{attempts} failed, retrying in {delay}s...")
        time.sleep(delay)
    raise last


def link_issues(auth, inward_key, outward_key):
    body = {
        "type": {"name": LINK_TYPE_NAME},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key},
    }
    r = requests.post(
        f"{JIRA_BASE}/rest/api/3/issueLink", auth=auth, json=body, timeout=30
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"issueLink {r.status_code}: {r.text[:500]}")


MD_STRIP_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)?\s*(.*?)\s*$")


def clean_md_line(line):
    """Strip markdown bullets/numbering and bold markers from a md line."""
    m = MD_STRIP_RE.match(line)
    text = m.group(1) if m else line.strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.strip()


def main():
    execute = "--execute" in sys.argv
    auth = get_auth()
    tickets = parse_md(MD_PATH)

    parents = [t for t in tickets if t["fields"].get("issue type", "").startswith("Task")]
    children = [t for t in tickets if "sub-task" in t["fields"].get("issue type", "").lower()]
    print(f"Parsed {len(parents)} parents, {len(children)} children from {MD_PATH.name}")
    assert len(parents) == 5, f"expected 5 parents, got {len(parents)}"
    assert len(children) == 23, f"expected 23 children, got {len(children)}"

    parent_payloads = [build_payload(t) for t in parents]
    child_payloads = {}
    for t in children:
        parent_fake = t["fields"]["parent key"].strip("`")
        fake, payload = build_payload(t, parent_key=parent_fake)
        child_payloads.setdefault(parent_fake, []).append((fake, payload))

    if not execute:
        print("\n=== DRY RUN (no changes made) ===")
        print(f"\nAll 5 parents will be linked to {PARENT_TICKET} ({LINK_TYPE_NAME})\n")
        for fake, p in parent_payloads:
            print(f"[{fake}] {p['fields']['summary']}")
            print(f"    priority={p['fields']['priority']['name']} "
                  f"assignee={p['fields'].get('assignee', {}).get('id')} "
                  f"reporter={p['fields'].get('reporter', {}).get('id')}")
            print(f"    desc blocks={len(p['fields']['description']['content'])}")
        for parent_fake, kids in child_payloads.items():
            print(f"\n--- Sub-tasks under {parent_fake} ---")
            for fake, p in kids:
                print(f"  [{fake}] {p['fields']['summary']}")
        print("\nRe-run with --execute to create in production Jira.")
        return

    mapping = {}

    # Resume support: parents already created in a previous run
    resume = {
        p.split("=")[1]: p.split("=")[2]
        for p in sys.argv[1:] if p.startswith("--resume-parent=")
    }
    if resume:
        mapping.update(resume)
        print(f"Resuming with existing parents: {resume}")
    else:
        print(f"\nCreating {len(parents)} parent tasks in {PROJECT_KEY}...")
        for fake, payload in parent_payloads:
            real = create_issue(auth, payload)
            mapping[fake] = real
            print(f"  {fake} -> {real} ({payload['fields']['summary']})")
            time.sleep(0.4)

    print("\nCreating sub-tasks...")
    for parent_fake, kids in child_payloads.items():
        real_parent = mapping[parent_fake]
        for fake, payload in kids:
            payload["fields"].pop("parent", None)
            real = create_subtask_with_retry(auth, payload, real_parent)
            mapping[fake] = real
            print(f"  {fake} -> {real} (under {real_parent})")
            time.sleep(0.4)

    print(f"\nLinking parents to {PARENT_TICKET} ({LINK_TYPE_NAME})...")
    for fake, real in mapping.items():
        if not fake.startswith("CCAI-PARENT"):
            continue
        link_issues(auth, PARENT_TICKET, real)
        print(f"  {PARENT_TICKET} relates to {real}")
        time.sleep(0.4)

    out = Path(__file__).resolve().parent / "wanda4_ticket_mapping.json"
    out.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"\nDone. Mapping written to {out}")


if __name__ == "__main__":
    main()
