"""Fetch comments for one or more Jira issues and merge into BigQuery table GSO.JiraComments.
Usage:
  python fetch_comments_oneoff.py CSM-1500 [CSM-1501 ...]

This script uses the same timestamp normalization as the initialsync pipeline.
It requires GOOGLE_APPLICATION_CREDENTIALS to be set or otherwise available.
"""
import sys, json, time, uuid, requests, random, os, pathlib
from datetime import datetime, timezone
from google.cloud import bigquery

_script_dir = pathlib.Path(__file__).resolve().parent
_root_dir = _script_dir.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S']
    for fmt in fmts:
        try:
            dt = datetime.strptime(ts, fmt)
            if fmt.endswith('Z') and '%z' not in fmt:
                dt = dt.replace(tzinfo=timezone.utc)
            if getattr(dt, 'tzinfo', None) is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
    return None

def fetch_comments_for_issue(base_url, issue_key, auth):
    url=f"{base_url}/rest/api/2/issue/{issue_key}/comment"
    start=0; size=100; out=[]; attempts=0
    while True:
        try:
            r = requests.get(url, auth=auth, params={'startAt':start,'maxResults':size}, timeout=120)
            r.raise_for_status(); data = r.json(); cm = data.get('comments', []); out.extend(cm)
            total = data.get('total', len(out))
            if start + len(cm) >= total:
                break
            start += len(cm)
            time.sleep(0.02 + random.uniform(0,0.05))
        except Exception as e:
            attempts += 1
            if attempts >= 5:
                break
            time.sleep(min(60, 2**attempts))
    return out

def make_rows_for_issue(key, comments):
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for c in comments:
        created = convert_ts(c.get('created'))
        updated = convert_ts(c.get('updated'))
        ref = updated or created
        if not ref: continue
        try:
            ref_dt = datetime.strptime(ref, '%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
        # We won't filter by window here - caller decides
        a = c.get('author', {})
        vis = c.get('visibility', {})
        rows.append({
            'Issue_Key': key,
            'Comment_ID': c.get('id'),
            'Author_Account_ID': a.get('accountId'),
            'Author_Display_Name': a.get('displayName'),
            'Created': created,
            'Updated': updated,
            'Body': c.get('body'),
            'Visibility_Type': vis.get('type'),
            'Visibility_Value': vis.get('value'),
            'SyncTime': now_str,
        })
    return rows

def merge_rows(client, dataset, table, rows):
    if not rows:
        return 0
    temp = f'JiraComments_temp_{uuid.uuid4().hex[:8]}'
    schema=[bigquery.SchemaField(n,t) for n,t in [
        ('Issue_Key','STRING'),('Comment_ID','STRING'),('Author_Account_ID','STRING'),('Author_Display_Name','STRING'),('Created','TIMESTAMP'),('Updated','TIMESTAMP'),('Body','STRING'),('Visibility_Type','STRING'),('Visibility_Value','STRING'),('SyncTime','TIMESTAMP')]]
    client.query(f"CREATE OR REPLACE TABLE `{dataset}.{temp}` (" + ','.join(f'`{c.name}` {c.field_type}' for c in schema) + ")").result()
    if not client.get_table(f"{dataset}.{temp}"): return 0
    # Insert rows
    ref = client.dataset(dataset).table(temp)
    errs = client.insert_rows_json(ref, rows)
    if errs:
        print('Insert errors:', errs); return 0
    merge = f"""
      MERGE `{dataset}.{table}` T USING (SELECT DISTINCT * FROM `{dataset}.{temp}`) S
      ON T.Comment_ID=S.Comment_ID AND T.Updated=S.Updated
      WHEN MATCHED THEN UPDATE SET T.Issue_Key=S.Issue_Key,T.Author_Account_ID=S.Author_Account_ID,T.Author_Display_Name=S.Author_Display_Name,T.Created=S.Created,T.Body=S.Body,T.Visibility_Type=S.Visibility_Type,T.Visibility_Value=S.Visibility_Value,T.SyncTime=S.SyncTime
      WHEN NOT MATCHED THEN INSERT (Issue_Key,Comment_ID,Author_Account_ID,Author_Display_Name,Created,Updated,Body,Visibility_Type,Visibility_Value,SyncTime)
      VALUES (S.Issue_Key,S.Comment_ID,S.Author_Account_ID,S.Author_Display_Name,S.Created,S.Updated,S.Body,S.Visibility_Type,S.Visibility_Value,S.SyncTime)
    """
    client.query(merge).result()
    # cleanup
    try: client.delete_table(f"{dataset}.{temp}")
    except Exception: pass
    return len(rows)

def main():
    if len(sys.argv) < 2:
        print('Usage: fetch_comments_oneoff.py ISSUE_KEY [ISSUE_KEY ...]')
        return
    keys = sys.argv[1:]
    cfg_path = os.path.join(str(_script_dir), 'config.json')
    cfg = None
    # try repo-level config as fallback
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path,'r',encoding='utf-8') as f: cfg = json.load(f)
        except Exception:
            cfg = None
    if not cfg:
        # try parent repo root
        root_cfg = os.path.join(str(_root_dir), 'config.json')
        if os.path.exists(root_cfg):
            with open(root_cfg,'r',encoding='utf-8') as f: cfg = json.load(f)
    if not cfg:
        print('No Jira config found (set JIRA_API_TOKEN/JIRA_USERNAME or provide config.json)'); return
    user = os.environ.get('JIRA_USERNAME') or cfg.get('jira_username')
    token = os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
    if not token:
        print('jira_api_token missing'); return
    auth = (user, token); base_url = 'https://consoleconnect.atlassian.net'
    client = bigquery.Client()
    dataset = 'GSO'; table = 'JiraComments'
    total = 0
    for k in keys:
        print('Fetching comments for', k)
        comments = fetch_comments_for_issue(base_url, k, auth)
        print('Found', len(comments), 'comments')
        rows = make_rows_for_issue(k, comments)
        n = merge_rows(client, dataset, table, rows)
        total += n
        print(f'Merged {n} rows for {k}')
    print('Done. Total merged rows:', total)

if __name__ == '__main__':
    main()
