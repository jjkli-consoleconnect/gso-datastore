"""Dry-run backfill count: scan all issues in a project, fetch comments, count comments within [ws,we).
Prints per-issue counts and a total. Does not access BigQuery.

Usage:
  python backfill_project_count.py --project "Customer Success Management" --ws "2025-08-14 16:00:00" --we "2025-08-16 16:00:00"
"""
import argparse, os, requests, time
from datetime import datetime

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S']
    from datetime import datetime as _dt, timezone as _tz
    for fmt in fmts:
        try:
            dt = _dt.strptime(ts, fmt)
            if fmt.endswith('Z') and '%z' not in fmt:
                dt = dt.replace(tzinfo=_tz.utc)
            if getattr(dt, 'tzinfo', None) is not None:
                dt = dt.astimezone(_tz.utc).replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
    return None


def fetch_all_issue_keys(base_url,proj,auth):
    keys=[]; start=0; max_results=100
    headers={'Accept':'application/json','Content-Type':'application/json'}
    while True:
        params={'jql': f'project = "{proj}"','startAt': start,'maxResults': max_results,'fields':'key'}
        r = requests.get(f"{base_url}/rest/api/3/search/jql", params=params, auth=auth, headers=headers, timeout=60)
        r.raise_for_status(); j=r.json()
        iss=j.get('issues',[])
        keys.extend([i.get('key') for i in iss if i.get('key')])
        total=j.get('total',0)
        start += len(iss)
        if start>=total:
            break
        time.sleep(0.05)
    return keys


def fetch_comments_for_issue(base_url,issue_key,auth):
    url=f"{base_url}/rest/api/2/issue/{issue_key}/comment"; start=0; size=100; out=[]
    while True:
        r = requests.get(url, auth=auth, params={'startAt':start,'maxResults':size}, timeout=60)
        r.raise_for_status(); data=r.json(); cm=data.get('comments',[]); out.extend(cm)
        total=data.get('total',len(out))
        if start+len(cm)>=total: break
        start+=len(cm); time.sleep(0.02)
    return out


def rows_from_comments(issue_key, comments, ws_dt, we_dt):
    rows=[]
    for c in comments:
        created = convert_ts(c.get('created'))
        updated = convert_ts(c.get('updated'))
        ref = updated or created
        if not ref: continue
        try: ref_dt=datetime.strptime(ref, '%Y-%m-%d %H:%M:%S')
        except Exception: continue
        if not (ws_dt <= ref_dt < we_dt): continue
        rows.append(c.get('id'))
    return rows


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--project', required=True); parser.add_argument('--ws', required=True); parser.add_argument('--we', required=True); args=parser.parse_args()
    proj=args.project; ws=args.ws; we=args.we
    try:
        ws_dt=datetime.strptime(ws, '%Y-%m-%d %H:%M:%S')
        we_dt=datetime.strptime(we, '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print('Window parse error', e); return
    user=os.environ.get('JIRA_USERNAME'); token=os.environ.get('JIRA_API_TOKEN')
    if not user or not token:
        print('Missing JIRA creds in env'); return
    auth=(user, token); base_url='https://consoleconnect.atlassian.net'

    print('Fetching all issue keys for project', proj)
    keys = fetch_all_issue_keys(base_url, proj, auth)
    print('Total issues found', len(keys))

    total=0; nonzero=0
    for idx,k in enumerate(keys, start=1):
        comments = []
        try:
            comments = fetch_comments_for_issue(base_url, k, auth)
        except Exception as e:
            print('Failed fetching comments for', k, e)
            continue
        ids = rows_from_comments(k, comments, ws_dt, we_dt)
        if ids:
            nonzero += 1
            total += len(ids)
            print(f'{k}: {len(ids)} comments -> {ids[:5]}')
        if idx % 200 == 0:
            print('Progress', idx, '/', len(keys))
    print('Summary: issues with matches=', nonzero, 'total comments in window=', total)

if __name__=='__main__':
    main()
