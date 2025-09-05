"""Dry-run across full project list: for each project, validate visibility and fetch a sample page of issues for a historic window.
This script does not perform any BigQuery writes.
"""
import logging, os
from datetime import datetime, timedelta, timezone
import main

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

cfg = main.load_config()
if not cfg:
    logging.error('No config available; aborting dry-run')
    raise SystemExit(1)

user = os.environ.get('JIRA_USERNAME') or cfg.get('jira_username')
token = os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
if not token:
    logging.error('No JIRA_API_TOKEN available; aborting dry-run')
    raise SystemExit(1)

auth = (user, token)

# Load projects from repo JQL file or other candidates
projects = main.load_projects_from_file([])
if not projects:
    logging.error('No projects found to dry-run; aborting')
    raise SystemExit(1)

logging.info(f'Dry-run will exercise {len(projects)} projects')

now = datetime.now(timezone.utc)
# Use a safe historic window to avoid near-now tiny-window skipping: 8->7 days ago
ws = now - timedelta(days=8)
we = now - timedelta(days=7)

for proj in projects:
    logging.info(f'Project: {proj} - preflight validate')
    ok, sc, msg = main.preflight_validate_project(auth, proj)
    if not ok:
        logging.warning(f'Preflight failed for "{proj}" status={sc} detail={msg}; skipping')
        continue
    proj_clause = f'project = "{proj}"' if any(ch in proj for ch in [' ','&']) else f'project = {proj}'
    jql = f'({proj_clause}) AND updated >= "{ws.strftime("%Y/%m/%d %H:%M")}" AND updated < "{we.strftime("%Y/%m/%d %H:%M")}"'
    logging.info(f'Executing sample JQL for {proj}: {jql}')
    res = main.fetch_issues_page(auth, jql, 0, 5)
    if res is None:
        logging.error(f'Failed to fetch issues for {proj}')
        continue
    total = res.get('total', 'unknown')
    issues = res.get('issues', [])
    logging.info(f'Project {proj}: total={total} sample_count={len(issues)}')
    for i in issues:
        k = i.get('key')
        s = i.get('fields', {}).get('summary')
        logging.info(f' - {k}: {s}')

logging.info('Dry-run finished')
