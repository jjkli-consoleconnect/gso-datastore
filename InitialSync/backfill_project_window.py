"""Backfill comments for a project within a specified UTC window.
Scans all issues in the project, fetches comments for each issue, keeps comments whose created/updated
timestamp is inside [ws, we), and MERGEs them into GSO.JiraComments.

Usage:
  python backfill_project_window.py --project "Customer Success Management" --ws "2025-08-14 16:00:00" --we "2025-08-16 16:00:00"

This script uses env vars JIRA_USERNAME and JIRA_API_TOKEN for Jira auth and GOOGLE_APPLICATION_CREDENTIALS for BigQuery.
"""
import argparse, os, requests, time, uuid, json
from datetime import datetime, timezone
from google.cloud import bigquery

# Minimal helpers copied from main pipeline

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S']
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


def create_or_replace_table(client,dataset,table,schema):
    try:
        ddl=f"CREATE OR REPLACE TABLE `{dataset}.{table}` ("+','.join(f'`{c.name}` {c.field_type}' for c in schema)+")"
        client.query(ddl).result(); return True
    except Exception as e:
        print('Create table failed', e); return False


def table_exists(client,dataset,table):
    try:
        client.get_table(f"{dataset}.{table}"); return True
    except Exception:
        return False


def insert_rows_with_retry(client,dataset,table,rows,schema,retries=6,delay=5):
    if not rows: return True
    ref=client.dataset(dataset).table(table)
    for attempt in range(retries):
        try:
            errs=client.insert_rows_json(ref,rows)
            if not errs: return True
            print('Insert errors', errs)
        except Exception as e:
            msg=str(e)
            if 'not found' in msg.lower():
                print('Temp table missing; recreating')
                if not create_or_replace_table(client,dataset,table,schema) or not table_exists(client,dataset,table): return False
                time.sleep(2)
            else:
                print('Insert exception', e)
        if attempt<retries-1: time.sleep(delay)
    return False


def delete_table_quiet(client,dataset,table):
    try: client.delete_table(f"{dataset}.{table}")
    except Exception: pass


def fetch_all_issue_keys(base_url,proj,auth):
    # Paginate search for all keys in project
    keys=[]; start=0; max_results=100
    headers={'Accept':'application/json','Content-Type':'application/json'}
    payload={'jql': f'project = "{proj}"','startAt': start,'maxResults': max_results,'fields':['key']}
    while True:
        payload['startAt']=start
        r = requests.post(f"{base_url}/rest/api/2/search", json=payload, auth=auth, headers=headers, timeout=60)
        r.raise_for_status(); j=r.json()
        iss=j.get('issues',[])
        keys.extend([i.get('key') for i in iss if i.get('key')])
        total=j.get('total',0)
        start += len(iss)
        if start>=total: break
        time.sleep(0.1)
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
    rows=[]; now_str=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    for c in comments:
        created = convert_ts(c.get('created'))
        updated = convert_ts(c.get('updated'))
        ref = updated or created
        if not ref: continue
        try: ref_dt=datetime.strptime(ref, '%Y-%m-%d %H:%M:%S')
        except Exception: continue
        if not (ws_dt <= ref_dt < we_dt): continue
        a=c.get('author',{})
        vis=c.get('visibility',{})
        rows.append({
            'Issue_Key': issue_key,
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
    client=bigquery.Client(); dataset='GSO'; table='JiraComments'

    temp=f'JiraComments_temp_backfill_{uuid.uuid4().hex[:8]}'
    schema=[bigquery.SchemaField(n,t) for n,t in [
        ('Issue_Key','STRING'),('Comment_ID','STRING'),('Author_Account_ID','STRING'),('Author_Display_Name','STRING'),('Created','TIMESTAMP'),('Updated','TIMESTAMP'),('Body','STRING'),('Visibility_Type','STRING'),('Visibility_Value','STRING'),('SyncTime','TIMESTAMP')]]
    if not table_exists(client,dataset,table):
        if not create_or_replace_table(client,dataset,table,schema):
            print('Failed to ensure target table'); return
    if not create_or_replace_table(client,dataset,temp,schema) or not table_exists(client,dataset,temp):
        print('Failed to create temp table'); return

    print('Fetching all issue keys for project', proj)
    keys = fetch_all_issue_keys(base_url, proj, auth)
    print('Total issues found', len(keys))

    buf=[]; batch=1000; inserted=0
    for idx,k in enumerate(keys, start=1):
        try:
            comments = fetch_comments_for_issue(base_url, k, auth)
        except Exception as e:
            print('Failed fetching comments for', k, e); comments=[]
        rows = rows_from_comments(k, comments, ws_dt, we_dt)
        if rows:
            buf.extend(rows)
            if len(buf)>=batch:
                ok=insert_rows_with_retry(client,dataset,temp,buf,schema)
                if not ok:
                    delete_table_quiet(client,dataset,temp); print('Insert failed'); return
                inserted+=len(buf); buf=[]
        if idx % 100 == 0:
            print('Progress', idx, '/', len(keys), 'inserted so far', inserted)
        time.sleep(0.02)
    if buf:
        if not insert_rows_with_retry(client,dataset,temp,buf,schema): delete_table_quiet(client,dataset,temp); print('Insert failed'); return
        inserted+=len(buf); buf=[]

    print('Rows staged in temp', inserted)
    merge=f"""
      MERGE `{dataset}.{table}` T USING (SELECT DISTINCT * FROM `{dataset}.{temp}`) S
      ON T.Comment_ID=S.Comment_ID AND T.Updated=S.Updated
      WHEN MATCHED THEN UPDATE SET T.Issue_Key=S.Issue_Key,T.Author_Account_ID=S.Author_Account_ID,T.Author_Display_Name=S.Author_Display_Name,T.Created=S.Created,T.Body=S.Body,T.Visibility_Type=S.Visibility_Type,T.Visibility_Value=S.Visibility_Value,T.SyncTime=S.SyncTime
      WHEN NOT MATCHED THEN INSERT (Issue_Key,Comment_ID,Author_Account_ID,Author_Display_Name,Created,Updated,Body,Visibility_Type,Visibility_Value,SyncTime)
      VALUES (S.Issue_Key,S.Comment_ID,S.Author_Account_ID,S.Author_Display_Name,S.Created,S.Updated,S.Body,S.Visibility_Type,S.Visibility_Value,S.SyncTime)
    """
    try:
        client.query(merge).result()
    except Exception as e:
        delete_table_quiet(client,dataset,temp); print('Merge failed', e); return
    delete_table_quiet(client,dataset,temp)
    print('Backfill completed. Rows merged (staged):', inserted)

if __name__=='__main__':
    main()
