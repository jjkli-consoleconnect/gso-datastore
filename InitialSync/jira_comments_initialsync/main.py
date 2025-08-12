"""Unified comments pipeline with changelog resiliency (rate limiting, adaptive shrink, degraded status)."""
import argparse, json, logging, time, uuid, requests, random, threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery

DEBUG=False
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Adaptive thresholds
ADAPT_HIGH_ROWS=50000
ADAPT_MEDIUM_ROWS=15000
ADAPT_LOW_ROWS=2000
ADAPT_GROW_CONSECUTIVE=3
MIN_SHRINK_HOURS=6
MAX_GROW_DAYS=7

OVERLAP_MINUTES=10
FAILURE_RATIO_DEGRADED=0.02

RATE_BUCKET_CAPACITY=120
RATE_BUCKET_REFILL_PER_SEC=2
RATE_MIN_SLEEP=0.05
JITTER_MAX_SECONDS=0.3
MAX_COMMENT_ATTEMPTS=5
SECOND_PASS_MAX_WORKERS=4
RATE_SHRINK_DETAIL_429=25
RATE_SHRINK_SEARCH_429=8
RATE_SHRINK_FACTOR=0.5

DETAIL_MIN_WORKERS=4
DETAIL_MAX_WORKERS=24
CURRENT_DETAIL_WORKERS=16
DETAIL_SCALE_DOWN_FACTOR=0.6
DETAIL_SCALE_UP_FACTOR=1.2
DETAIL_SCALE_UP_NO429_WINDOWS=2

SEARCH_429_COUNT=0
DETAIL_429_COUNT=0
_NO429_STREAK=0

LOG_BUFFER=[]

class TokenBucket:
    def __init__(self, capacity, refill_per_sec):
        self.capacity=capacity; self.tokens=capacity; self.refill=refill_per_sec; self.last=time.time(); self.lock=threading.Lock()
    def take(self, amount=1):
        while True:
            with self.lock:
                now_t=time.time(); elapsed=now_t-self.last
                if elapsed>0:
                    add=elapsed*self.refill
                    if add>0:
                        self.tokens=min(self.capacity,self.tokens+add); self.last=now_t
                if self.tokens>=amount:
                    self.tokens-=amount; return True
            time.sleep(RATE_MIN_SLEEP)

RATE_LIMITER=TokenBucket(RATE_BUCKET_CAPACITY,RATE_BUCKET_REFILL_PER_SEC)

def load_config():
    try:
        with open('config.json') as f: return json.load(f)
    except FileNotFoundError:
        logging.error('config.json not found'); return None

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S']
    for fmt in fmts:
        try:
            dt=datetime.strptime(ts,fmt)
            if dt.tzinfo: dt=dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception: continue
    return None

def create_or_replace_table(client,dataset,table,schema):
    try:
        ddl=f"CREATE OR REPLACE TABLE `{dataset}.{table}` ("+','.join(f'`{c.name}` {c.field_type}' for c in schema)+")"; client.query(ddl).result(); return True
    except Exception as e:
        logging.exception(f'Create table failed {dataset}.{table}: {e}'); return False

def table_exists(client,dataset,table):
    try: client.get_table(f"{dataset}.{table}"); return True
    except Exception: return False

def wait_for_table(client,dataset,table,retries=12,delay=3):
    for _ in range(retries):
        if table_exists(client,dataset,table): return True
        time.sleep(delay)
    return False

def insert_rows_with_retry(client,dataset,table,rows,schema,retries=6,delay=5):
    if not rows: return True
    ref=client.dataset(dataset).table(table)
    for attempt in range(retries):
        try:
            errs=client.insert_rows_json(ref,rows)
            if not errs: return True
            logging.error(f'Insert errors {errs}')
        except Exception as e:
            if 'Not found' in str(e):
                if not create_or_replace_table(client,dataset,table,schema) or not wait_for_table(client,dataset,table): return False
            else:
                logging.exception(f'Insert exception: {e}')
        if attempt<retries-1: time.sleep(delay)
    return False

def delete_table_quiet(client,dataset,table):
    try: client.delete_table(f"{dataset}.{table}")
    except Exception: pass

def fetch_issues_page(search_url,auth,headers,jql,start_at,max_results):
    global SEARCH_429_COUNT
    payload=json.dumps({'jql':jql,'startAt':start_at,'maxResults':max_results,'fields':['key']})
    for attempt in range(5):
        try:
            RATE_LIMITER.take(); r=requests.post(search_url,headers=headers,auth=auth,data=payload,timeout=300)
            if r.status_code==429:
                SEARCH_429_COUNT+=1; ra=int(r.headers.get('Retry-After',30)); time.sleep(ra+random.uniform(0,JITTER_MAX_SECONDS)); continue
            r.raise_for_status(); return r.json()
        except requests.exceptions.Timeout:
            time.sleep(15)
        except requests.RequestException:
            if attempt<4: time.sleep(8)
            else: return None
    return None

def fetch_comments_for_issue(base_url,issue_key,auth):
    global DETAIL_429_COUNT
    url=f"{base_url}/rest/api/2/issue/{issue_key}/comment"; start=0; size=100; out=[]; attempts=0
    while True:
        try:
            RATE_LIMITER.take(); r=requests.get(url,auth=auth,params={'startAt':start,'maxResults':size},timeout=180)
            if r.status_code==429:
                DETAIL_429_COUNT+=1; ra=int(r.headers.get('Retry-After',10)); time.sleep(ra+random.uniform(0,JITTER_MAX_SECONDS)); continue
            r.raise_for_status(); data=r.json(); cm=data.get('comments',[]); out.extend(cm); total=data.get('total',len(out))
            if start+len(cm)>=total: break
            start+=len(cm); time.sleep(0.02+random.uniform(0,0.05))
        except Exception:
            attempts+=1
            if attempts>=MAX_COMMENT_ATTEMPTS: break
            back=min(60,2**attempts)+random.uniform(0,JITTER_MAX_SECONDS); time.sleep(back)
    return out

def fetch_comments_batch(base_url,keys,auth,max_workers=None):
    if max_workers is None: max_workers=CURRENT_DETAIL_WORKERS
    res={}
    def worker(k): return k, fetch_comments_for_issue(base_url,k,auth)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fmap={ex.submit(worker,k):k for k in keys}
        for fut in as_completed(fmap):
            k=fmap[fut]
            try: kk,data=fut.result(); res[kk]=data
            except Exception: res[k]=[]
            time.sleep(0.01+random.uniform(0,0.03))
    return res

def generate_rows(issues,cmap,ws,we):
    now_str=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    for issue in issues:
        key=issue.get('key') if issue else None
        if not key: continue
        for c in cmap.get(key,[]):
            created=convert_ts(c.get('created')); updated=convert_ts(c.get('updated')); ref=updated or created
            if not ref: continue
            try: ref_dt=datetime.strptime(ref,'%Y-%m-%d %H:%M:%S')
            except Exception: continue
            if not (ws <= ref_dt < we): continue
            a=c.get('author',{}); vis=c.get('visibility',{})
            yield {
                'Issue_Key': key,'Comment_ID': c.get('id'),'Author_Account_ID': a.get('accountId'),'Author_Display_Name': a.get('displayName'),
                'Created': created,'Updated': updated,'Body': c.get('body'),'Visibility_Type': vis.get('type'),'Visibility_Value': vis.get('value'),'SyncTime': now_str,
            }

def sync_window(base_url,jql,auth,client,dataset,table,ws,we):
    temp=f'JiraComments_temp_{uuid.uuid4()}'
    schema=[bigquery.SchemaField(n,t) for n,t in [
        ('Issue_Key','STRING'),('Comment_ID','STRING'),('Author_Account_ID','STRING'),('Author_Display_Name','STRING'),('Created','TIMESTAMP'),('Updated','TIMESTAMP'),('Body','STRING'),('Visibility_Type','STRING'),('Visibility_Value','STRING'),('SyncTime','TIMESTAMP')]]
    if not table_exists(client,dataset,table): create_or_replace_table(client,dataset,table,schema)
    else:
        try: client.query(f"ALTER TABLE `{dataset}.{table}` ADD COLUMN IF NOT EXISTS SyncTime TIMESTAMP").result()
        except Exception: pass
    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp): return False,0
    search_url=f"{base_url}/rest/api/2/search"; headers={'Accept':'application/json','Content-Type':'application/json'}
    start=0; max_results=100; total=float('inf'); buf=[]; batch=1000; inserted=0
    while start<total:
        data=fetch_issues_page(search_url,auth,headers,jql,start,max_results)
        if data is None: delete_table_quiet(client,dataset,temp); return False,inserted
        issues=data.get('issues',[]); total=data.get('total',0)
        if not issues: break
        keys=[i.get('key') for i in issues if i.get('key')]
        cmap=fetch_comments_batch(base_url,keys,auth)
        for row in generate_rows(issues,cmap,ws,we):
            buf.append(row)
            if len(buf)>=batch:
                if not insert_rows_with_retry(client,dataset,temp,buf,schema): delete_table_quiet(client,dataset,temp); return False,inserted
                inserted+=len(buf); buf=[]
        if buf:
            if not insert_rows_with_retry(client,dataset,temp,buf,schema): delete_table_quiet(client,dataset,temp); return False,inserted
            inserted+=len(buf); buf=[]
        start+=len(issues); time.sleep(1)
    merge=f"""
      MERGE `{dataset}.{table}` T USING (SELECT DISTINCT * FROM `{dataset}.{temp}`) S
      ON T.Comment_ID=S.Comment_ID AND T.Updated=S.Updated
      WHEN MATCHED THEN UPDATE SET T.Issue_Key=S.Issue_Key,T.Author_Account_ID=S.Author_Account_ID,T.Author_Display_Name=S.Author_Display_Name,T.Created=S.Created,T.Body=S.Body,T.Visibility_Type=S.Visibility_Type,T.Visibility_Value=S.Visibility_Value,T.SyncTime=S.SyncTime
      WHEN NOT MATCHED THEN INSERT (Issue_Key,Comment_ID,Author_Account_ID,Author_Display_Name,Created,Updated,Body,Visibility_Type,Visibility_Value,SyncTime)
      VALUES (S.Issue_Key,S.Comment_ID,S.Author_Account_ID,S.Author_Display_Name,S.Created,S.Updated,S.Body,S.Visibility_Type,S.Visibility_Value,S.SyncTime)
    """
    try: client.query(merge).result()
    except Exception as e: delete_table_quiet(client,dataset,temp); logging.exception(f'Merge failed: {e}'); return False,inserted
    delete_table_quiet(client,dataset,temp); return True,inserted

def log_buf(pipeline,run_id,level,msg,fn=None,details=None):
    LOG_BUFFER.append({'Timestamp':datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),'PipelineName':pipeline,'RunID':run_id,'LogLevel':level,'Message':msg,'FunctionName':fn,'Details':details})

def flush_logs(client,dataset,table):
    if not LOG_BUFFER: return
    temp='PipelineLogs_temp_comments'
    schema=[bigquery.SchemaField(n,t) for n,t in [('Timestamp','TIMESTAMP'),('PipelineName','STRING'),('RunID','STRING'),('LogLevel','STRING'),('Message','STRING'),('FunctionName','STRING'),('Details','STRING')]]
    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp): return
    if not insert_rows_with_retry(client,dataset,temp,LOG_BUFFER,schema): return
    merge=f"MERGE `{dataset}.{table}` T USING (SELECT * FROM `{dataset}.{temp}`) S ON T.Timestamp=S.Timestamp AND T.RunID=S.RunID AND T.Message=S.Message WHEN MATCHED THEN UPDATE SET T.PipelineName=S.PipelineName,T.LogLevel=S.LogLevel,T.FunctionName=S.FunctionName,T.Details=S.Details WHEN NOT MATCHED THEN INSERT (Timestamp,PipelineName,RunID,LogLevel,Message,FunctionName,Details) VALUES (S.Timestamp,S.PipelineName,S.RunID,S.LogLevel,S.Message,S.FunctionName,S.Details)"
    client.query(merge).result(); delete_table_quiet(client,dataset,temp)

def main():
    cfg=load_config();
    if not cfg: return
    dataset='GSO'; table='JiraComments'; progress=f'{table}_progress'; log_table='PipelineLogs'; pipeline='jira_comments'; run_id=str(uuid.uuid4()); base_days=7
    min_start=datetime(2024,7,1); client=bigquery.Client(); now=datetime.utcnow()
    prog_schema=[bigquery.SchemaField(n,t) for n,t in [ ('WindowStart','TIMESTAMP'),('WindowEnd','TIMESTAMP'),('Status','STRING'),('LastRun','TIMESTAMP'),('Projects','STRING'),('Project','STRING'),('RowCount','INT64'),('Search429','INT64'),('Detail429','INT64')]]
    if not table_exists(client,dataset,progress): create_or_replace_table(client,dataset,progress,prog_schema)
    else:
        for col,ctype in [('Project','STRING'),('RowCount','INT64'),('Search429','INT64'),('Detail429','INT64')]:
            try: client.query(f"ALTER TABLE `{dataset}.{progress}` ADD COLUMN IF NOT EXISTS {col} {ctype}").result()
            except Exception: pass
    default_projects=[ 'Managed Security Services','GS&O Tool Automation','GS&O Data Analytics','IOT CE','Google Contact Center AI Solution','GS&O Knowledge Consolidation' ]
    parser=argparse.ArgumentParser(); parser.add_argument('--project'); parser.add_argument('--projects'); args,_=parser.parse_known_args()
    if args.projects: req=[p.strip() for p in args.projects.split(',') if p.strip()]; projects=[p for p in default_projects if p in req]
    elif args.project: projects=[p for p in default_projects if p==args.project]
    else: projects=default_projects
    if not projects: return
    user=cfg.get('jira_username') or 'jjkli@consoleconnect.com'; token=cfg.get('jira_api_token')
    if not token: logging.error('jira_api_token missing'); return
    auth=(user,token); base_url='https://consoleconnect.atlassian.net'
    for proj in projects:
        last_completed_start=None
        while True:
            ws=None; we=None
            q=f"SELECT WindowStart,WindowEnd FROM `{dataset}.{progress}` WHERE Project=@p AND Status NOT IN ('complete','degraded') ORDER BY WindowStart ASC LIMIT 1"
            cfgq=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter('p','STRING',proj)])
            try:
                rows=client.query(q,job_config=cfgq).result()
                for r in rows: ws=r.WindowStart; we=r.WindowEnd; break
            except Exception: pass
            adaptive=base_days
            try:
                hist=list(client.query(f"SELECT RowCount,WindowStart,WindowEnd, IFNULL(Search429,0) Search429, IFNULL(Detail429,0) Detail429 FROM `{dataset}.{progress}` WHERE Project=@p AND Status IN ('complete','degraded') ORDER BY WindowEnd DESC LIMIT 5",job_config=cfgq).result())
                if hist:
                    last=hist[0]; last_count=last.RowCount or 0
                    try: last_hours=max(0.01,(last.WindowEnd-last.WindowStart).total_seconds()/3600.0)
                    except Exception: last_hours=base_days*24
                    base_hours=base_days*24; min_hours=MIN_SHRINK_HOURS; candidate_hours=last_hours
                    ls429=getattr(last,'Search429',0) or 0; ld429=getattr(last,'Detail429',0) or 0
                    if (ld429>=RATE_SHRINK_DETAIL_429) or (ls429>=RATE_SHRINK_SEARCH_429):
                        candidate_hours=max(min_hours,last_hours*RATE_SHRINK_FACTOR)
                    elif last_count>ADAPT_HIGH_ROWS and last_hours>min_hours:
                        candidate_hours=max(min_hours,last_hours/2.0)
                    elif last_count>ADAPT_MEDIUM_ROWS and last_hours>12:
                        candidate_hours=max(12,last_hours/1.5)
                    else:
                        if last_hours<base_hours:
                            recent=hist[:ADAPT_GROW_CONSECUTIVE]
                            if len(recent)==ADAPT_GROW_CONSECUTIVE and all((r.RowCount or 0)<ADAPT_LOW_ROWS for r in recent):
                                candidate_hours=min(base_hours,last_hours*2.0)
                    candidate_hours=max(min_hours,min(candidate_hours,base_hours)); adaptive=candidate_hours/24.0
            except Exception: pass
            if ws and we: cand=we
            else:
                latest=None
                try:
                    lr=client.query(f"SELECT WindowEnd FROM `{dataset}.{progress}` WHERE Project=@p ORDER BY WindowEnd DESC LIMIT 1",job_config=cfgq).result()
                    for r in lr: latest=r.WindowEnd; break
                except Exception: pass
                if latest:
                    overlap=timedelta(minutes=OVERLAP_MINUTES)
                    latest_naive=latest.replace(tzinfo=None) if getattr(latest,'tzinfo',None) else latest
                    last_completed_naive=last_completed_start.replace(tzinfo=None) if (last_completed_start and getattr(last_completed_start,'tzinfo',None)) else last_completed_start
                    cand_start=latest_naive-overlap
                    if last_completed_naive and cand_start<=last_completed_naive: cand_start=latest_naive
                    if last_completed_naive and (latest_naive-last_completed_naive)<=overlap*2: cand_start=latest_naive
                    if cand_start<min_start: cand_start=min_start
                    ws=cand_start
                else: ws=min_start
                cand=ws+timedelta(days=adaptive)
            ws_naive=ws.replace(tzinfo=None) if getattr(ws,'tzinfo',None) else ws
            now_naive=now.replace(tzinfo=None)
            cand_naive=cand.replace(tzinfo=None) if getattr(cand,'tzinfo',None) else cand
            we=min(cand_naive,now_naive)
            if ws_naive>=now_naive: break
            proj_clause=f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            jql=f"({proj_clause}) AND updated >= \"{ws_naive.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
            try:
                merge=(
                    f"MERGE `{dataset}.{progress}` T USING (SELECT TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S')}') AS WindowStart, TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS WindowEnd, '{proj}' AS Project) S "
                    "ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project "
                    "WHEN MATCHED THEN UPDATE SET Status='in_progress', LastRun=CURRENT_TIMESTAMP(), Project=S.Project "
                    "WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project) VALUES (S.WindowStart,S.WindowEnd,'in_progress',CURRENT_TIMESTAMP(),S.Project)"
                ); client.query(merge).result()
            except Exception: break
            SUCCESS=False; rc=0
            global SEARCH_429_COUNT, DETAIL_429_COUNT, CURRENT_DETAIL_WORKERS, _NO429_STREAK
            SEARCH_429_COUNT=0; DETAIL_429_COUNT=0
            try: SUCCESS,rc=sync_window(base_url,jql,auth,client,dataset,table,ws_naive,we)
            except Exception as e: log_buf(pipeline,run_id,'ERROR',f'Fatal {proj} {ws_naive}->{we} {e}','main',str(e))
            degraded=False
            if SUCCESS:
                ratio=DETAIL_429_COUNT/max(1,rc)
                if ratio>FAILURE_RATIO_DEGRADED: degraded=True
            status='degraded' if degraded else ('complete' if SUCCESS else 'failed')
            upd=(
                f"UPDATE `{dataset}.{progress}` SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc}, Search429={SEARCH_429_COUNT}, Detail429={DETAIL_429_COUNT} "
                f"WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND Status!='complete'"
            ); client.query(upd).result()
            if status in ('complete','degraded'):
                last_completed_start=ws_naive
                if (SEARCH_429_COUNT>0 or DETAIL_429_COUNT>0):
                    CURRENT_DETAIL_WORKERS=max(DETAIL_MIN_WORKERS,int(CURRENT_DETAIL_WORKERS*DETAIL_SCALE_DOWN_FACTOR)); _NO429_STREAK=0
                else:
                    _NO429_STREAK+=1
                    if _NO429_STREAK>=DETAIL_SCALE_UP_NO429_WINDOWS and CURRENT_DETAIL_WORKERS<DETAIL_MAX_WORKERS:
                        CURRENT_DETAIL_WORKERS=min(DETAIL_MAX_WORKERS,max(CURRENT_DETAIL_WORKERS+1,int(CURRENT_DETAIL_WORKERS*DETAIL_SCALE_UP_FACTOR))); _NO429_STREAK=0
            if not SUCCESS:
                try: span_hours=(we-ws_naive).total_seconds()/3600.0
                except Exception: span_hours=0
                if span_hours>(MIN_SHRINK_HOURS+0.05):
                    new_span=max(MIN_SHRINK_HOURS,span_hours*RATE_SHRINK_FACTOR); new_end=ws_naive+timedelta(hours=new_span)
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET WindowEnd=TIMESTAMP('{new_end.strftime('%Y-%m-%d %H:%M:%S')}'), Status='failed' WHERE Project='{proj}' "
                            f"AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING)"
                        ).result();
                        continue
                    except Exception: break
                else:
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET Status='degraded' WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND Status='failed'"
                        ).result()
                    except Exception: pass
                    break
    log_buf(pipeline,run_id,'INFO','Comments pipeline finished','main'); flush_logs(client,dataset,log_table)

if __name__=='__main__':
    main()
