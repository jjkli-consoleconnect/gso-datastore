"""Jira Tickets Initial Sync (Refactored)
Per-project adaptive window backfill (base 7d, shrink to 6h, regrow) aligned with changelog & comments pipelines.
Temp staging + MERGE, progress ledger (Project, RowCount), buffered logging, SLA metrics extraction.
"""
import json, logging, time, uuid, requests, argparse, random, threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery

DEBUG=False
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG_BUFFER=[]

# Adaptive thresholds
ADAPT_HIGH_ROWS=50000
ADAPT_MEDIUM_ROWS=15000
ADAPT_LOW_ROWS=2000
ADAPT_GROW_CONSECUTIVE=3
MIN_SHRINK_HOURS=6
MAX_GROW_DAYS=7

# Resiliency / rate limit controls
OVERLAP_MINUTES=10
FAILURE_RATIO_DEGRADED=0.02
RATE_BUCKET_CAPACITY=120
RATE_BUCKET_REFILL_PER_SEC=2
RATE_MIN_SLEEP=0.05
JITTER_MAX_SECONDS=0.3
MAX_DETAIL_ATTEMPTS=5
TICKET_MIN_WORKERS=4
TICKET_MAX_WORKERS=24
CURRENT_TICKET_WORKERS=16
TICKET_SCALE_DOWN_FACTOR=0.6
TICKET_SCALE_UP_FACTOR=1.2
TICKET_SCALE_UP_NO429_WINDOWS=2
RATE_SHRINK_DETAIL_429=25
RATE_SHRINK_SEARCH_429=8
RATE_SHRINK_FACTOR=0.5

SEARCH_429_COUNT=0
DETAIL_429_COUNT=0
_NO429_STREAK=0

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

# Custom / SLA fields
SR_REF_JIRA_ID='customfield_10382'
SR_REF_BQ_NAME='SR_Ref'
ESCALATION_FIELD='customfield_11171'
SLA_FIELDS_MAP={
    'TimeToFirstResponse':'customfield_10627',
    'TimeToResolve':'customfield_10686',
    'TimeToResolution':'customfield_10668',
    'TimeToApproveNormalChange':'customfield_10640',
    'ProlongCase':'customfield_10560',
    'TimeToCloseAfterResolution':'customfield_10552',
}

# ---------------- Utilities ----------------
def load_config():
    try:
        with open('config.json') as f: return json.load(f)
    except FileNotFoundError:
        logging.error('config.json not found'); return None

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%SZ']
    for fmt in fmts:
        try:
            dt=datetime.strptime(ts,fmt)
            if dt.tzinfo: dt=dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception: continue
    return None

def get_field_value(field):
    if field is None: return None
    if isinstance(field,dict): return field.get('value') or field.get('name') or field.get('displayName')
    if isinstance(field,list):
        return ', '.join([str((i.get('value') or i.get('name') or i.get('displayName')) if isinstance(i,dict) else i) for i in field])
    if isinstance(field,bool): return str(field)
    return str(field)

# ---------------- BigQuery helpers ----------------
def table_exists(client,dataset,table):
    try: client.get_table(f"{dataset}.{table}"); return True
    except Exception: return False

def create_or_replace_table(client,dataset,table,schema):
    try:
        cols=','.join(f'`{c.name}` {c.field_type}' for c in schema)
        client.query(f"CREATE OR REPLACE TABLE `{dataset}.{table}` ({cols})").result(); return True
    except Exception as e:
        logging.exception(f'Create/replace {dataset}.{table} failed: {e}'); return False

def wait_for_table(client,dataset,table,retries=10,delay=2):
    for _ in range(retries):
        if table_exists(client,dataset,table): return True
        time.sleep(delay)
    return False

def insert_rows_with_retry(client,dataset,table,rows,schema,retries=6,delay=6):
    if not rows: return True
    ref=client.dataset(dataset).table(table)
    for attempt in range(retries):
        try:
            errs=client.insert_rows_json(ref,rows)
            if not errs: return True
            logging.error(f'Insert errors attempt {attempt+1}: {errs}')
        except Exception as e:
            if 'Not found' in str(e):
                if not create_or_replace_table(client,dataset,table,schema) or not wait_for_table(client,dataset,table): return False
            else:
                logging.exception(f'Insert exception attempt {attempt+1}: {e}')
        if attempt<retries-1: time.sleep(delay)
    return False

def delete_table_quiet(client,dataset,table):
    try: client.delete_table(f"{dataset}.{table}")
    except Exception: pass

# ---------------- Jira fetch ----------------
BASE_URL='https://consoleconnect.atlassian.net'
SEARCH_URL=f'{BASE_URL}/rest/api/2/search'

def fetch_issues_page(auth,jql,start_at,max_results):
    global SEARCH_429_COUNT
    payload=json.dumps({'jql':jql,'startAt':start_at,'maxResults':max_results,'fields':['key']})
    headers={'Accept':'application/json','Content-Type':'application/json'}
    for attempt in range(5):
        try:
            RATE_LIMITER.take(); r=requests.post(SEARCH_URL,headers=headers,auth=auth,data=payload,timeout=300)
            if r.status_code==429:
                SEARCH_429_COUNT+=1; ra=int(r.headers.get('Retry-After',30)); time.sleep(ra+random.uniform(0,JITTER_MAX_SECONDS)); continue
            r.raise_for_status(); return r.json()
        except requests.exceptions.Timeout:
            time.sleep(15)
        except requests.RequestException:
            if attempt<4: time.sleep(10)
            else: return None
    return None

def fetch_issue_detail(issue_key,auth):
    global DETAIL_429_COUNT
    url=f'{BASE_URL}/rest/api/latest/issue/{issue_key}'
    attempts=0
    while True:
        try:
            RATE_LIMITER.take(); r=requests.get(url,auth=auth,timeout=120)
            if r.status_code==429:
                DETAIL_429_COUNT+=1; ra=int(r.headers.get('Retry-After',10)); time.sleep(ra+random.uniform(0,JITTER_MAX_SECONDS)); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            attempts+=1
            if attempts>=MAX_DETAIL_ATTEMPTS:
                logging.warning(f'Issue detail failed permanently {issue_key}: {e}'); return None
            back=min(60,2**attempts)+random.uniform(0,JITTER_MAX_SECONDS); time.sleep(back)

def extract_sla_metrics(sla_field):
    if not isinstance(sla_field,dict): return (None,None,None,None)
    cycles=sla_field.get('completedCycles',[]); n=len(cycles)
    if n==0: return (None,None,None,0)
    latest=cycles[-1]; start_time=latest.get('startTime'); breach_time=latest.get('breachTime'); goal_millis=latest.get('goalDuration',{}).get('millis')
    def parse(ts):
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%S%z'):
            try: return datetime.strptime(ts,fmt)
            except Exception: continue
        return None
    elapsed=None
    if start_time:
        sdt=parse(start_time)
        if breach_time:
            bdt=parse(breach_time)
            if sdt and bdt: elapsed=(bdt-sdt).total_seconds()/3600.0
        else:
            if sdt: elapsed=(datetime.utcnow()-sdt.replace(tzinfo=None)).total_seconds()/3600.0
    goal=goal_millis/3600000.0 if goal_millis else None
    breached=breach_time is not None
    return (elapsed,goal,breached,n)

def generate_ticket_rows(issue_keys,ws,we,auth):
    now_str=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    rows=[]
    def worker(k): return k, fetch_issue_detail(k,auth)
    with ThreadPoolExecutor(max_workers=min(CURRENT_TICKET_WORKERS,12)) as ex:
        fut_map={ex.submit(worker,k):k for k in issue_keys}
        for fut in as_completed(fut_map):
            k=fut_map[fut]
            try: _,detail=fut.result()
            except Exception:
                detail=None
            if not detail: continue
            fields=detail.get('fields',{})
            created=convert_ts(fields.get('created'))
            updated=convert_ts(fields.get('updated'))
            ref=updated or created
            if not ref: continue
            try: ref_dt=datetime.strptime(ref,'%Y-%m-%d %H:%M:%S')
            except Exception: continue
            if not (ws <= ref_dt < we): continue
            sla={}
            for name,jid in SLA_FIELDS_MAP.items():
                e,g,b,c=extract_sla_metrics(fields.get(jid)); sla[name]=(e,g,b,c)
            row={
                'Project': fields.get('project',{}).get('name'),
                'Key': k,
                'Summary': fields.get('summary'),
                'Status': fields.get('status',{}).get('name'),
                'Created': created,
                'Updated': updated,
                'Resolved': convert_ts(fields.get('resolutiondate')),
                'Reporter': get_field_value(fields.get('reporter')),
                'Assignee': get_field_value(fields.get('assignee')),
                'Component': [get_field_value(c) for c in fields.get('components',[])],
                'RemedyTicketNumber': [],
                'Links': get_field_value(fields.get('issuelinks')),
                SR_REF_BQ_NAME: get_field_value(fields.get(SR_REF_JIRA_ID)),
                'SyncTime': now_str,
                'AppSupEscalation': get_field_value(fields.get(ESCALATION_FIELD)),
            }
            for name,(e,g,b,c) in sla.items():
                row[f'{name}_Elapsed']=e; row[f'{name}_Goal']=g; row[f'{name}_Breached']=b; row[f'{name}_Cycles']=c
            rows.append(row)
    return rows

# ---------------- Window sync ----------------
def sync_tickets_window(jql,auth,client,dataset,table,ws,we):
    temp=f'JiraTickets_temp_{uuid.uuid4()}'
    schema=[bigquery.SchemaField(n,t,mode) for n,t,mode in [
        ('Project','STRING','NULLABLE'),
        ('Key','STRING','REQUIRED'),
        ('Summary','STRING','NULLABLE'),
        ('Status','STRING','NULLABLE'),
        ('Created','TIMESTAMP','NULLABLE'),
        ('Updated','TIMESTAMP','NULLABLE'),
        ('Resolved','TIMESTAMP','NULLABLE'),
        ('Reporter','STRING','NULLABLE'),
        ('Assignee','STRING','NULLABLE'),
        ('Component','STRING','REPEATED'),
        ('RemedyTicketNumber','STRING','REPEATED'),
        ('Links','STRING','NULLABLE'),
        (SR_REF_BQ_NAME,'STRING','NULLABLE'),
        ('SyncTime','TIMESTAMP','NULLABLE'),
        ('TimeToFirstResponse_Elapsed','FLOAT64','NULLABLE'),
        ('TimeToFirstResponse_Goal','FLOAT64','NULLABLE'),
        ('TimeToFirstResponse_Breached','BOOL','NULLABLE'),
        ('TimeToFirstResponse_Cycles','INT64','NULLABLE'),
        ('TimeToResolve_Elapsed','FLOAT64','NULLABLE'),
        ('TimeToResolve_Goal','FLOAT64','NULLABLE'),
        ('TimeToResolve_Breached','BOOL','NULLABLE'),
        ('TimeToResolve_Cycles','INT64','NULLABLE'),
        ('TimeToResolution_Elapsed','FLOAT64','NULLABLE'),
        ('TimeToResolution_Goal','FLOAT64','NULLABLE'),
        ('TimeToResolution_Breached','BOOL','NULLABLE'),
        ('TimeToResolution_Cycles','INT64','NULLABLE'),
        ('TimeToApproveNormalChange_Elapsed','FLOAT64','NULLABLE'),
        ('TimeToApproveNormalChange_Goal','FLOAT64','NULLABLE'),
        ('TimeToApproveNormalChange_Breached','BOOL','NULLABLE'),
        ('TimeToApproveNormalChange_Cycles','INT64','NULLABLE'),
        ('ProlongCase_Elapsed','FLOAT64','NULLABLE'),
        ('ProlongCase_Goal','FLOAT64','NULLABLE'),
        ('ProlongCase_Breached','BOOL','NULLABLE'),
        ('ProlongCase_Cycles','INT64','NULLABLE'),
        ('TimeToCloseAfterResolution_Elapsed','FLOAT64','NULLABLE'),
        ('TimeToCloseAfterResolution_Goal','FLOAT64','NULLABLE'),
        ('TimeToCloseAfterResolution_Breached','BOOL','NULLABLE'),
        ('TimeToCloseAfterResolution_Cycles','INT64','NULLABLE'),
        ('AppSupEscalation','STRING','NULLABLE'),
    ]]
    if not table_exists(client,dataset,table): create_or_replace_table(client,dataset,table,schema)
    else:
        try: client.query(f"ALTER TABLE `{dataset}.{table}` ADD COLUMN IF NOT EXISTS SyncTime TIMESTAMP").result()
        except Exception: pass
    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp): return False,0
    max_results=100; start=0; total=float('inf'); batch=500; buffer=[]; inserted=0
    while start<total:
        data=fetch_issues_page(auth,jql,start,max_results)
        if data is None:
            delete_table_quiet(client,dataset,temp); return False,inserted
        issues=data.get('issues',[]); total=data.get('total',0)
        if not issues: break
        issue_keys=[i.get('key') for i in issues if i.get('key')]
        rows=generate_ticket_rows(issue_keys,ws,we,auth)
        for r in rows:
            buffer.append(r)
            if len(buffer)>=batch:
                if not insert_rows_with_retry(client,dataset,temp,buffer,schema): delete_table_quiet(client,dataset,temp); return False,inserted
                inserted+=len(buffer); buffer=[]
        if buffer:
            if not insert_rows_with_retry(client,dataset,temp,buffer,schema): delete_table_quiet(client,dataset,temp); return False,inserted
            inserted+=len(buffer); buffer=[]
        start+=len(issues); time.sleep(1)
    merge=f"""MERGE `{dataset}.{table}` T USING (SELECT * FROM `{dataset}.{temp}`) S ON T.Key=S.Key AND (T.Updated=S.Updated OR (T.Updated IS NULL AND S.Updated IS NULL)) WHEN MATCHED THEN UPDATE SET Project=S.Project,Summary=S.Summary,Status=S.Status,Created=S.Created,Updated=S.Updated,Resolved=S.Resolved,Reporter=S.Reporter,Assignee=S.Assignee,Component=S.Component,RemedyTicketNumber=S.RemedyTicketNumber,Links=S.Links,{SR_REF_BQ_NAME}=S.{SR_REF_BQ_NAME},SyncTime=S.SyncTime,TimeToFirstResponse_Elapsed=S.TimeToFirstResponse_Elapsed,TimeToFirstResponse_Goal=S.TimeToFirstResponse_Goal,TimeToFirstResponse_Breached=S.TimeToFirstResponse_Breached,TimeToFirstResponse_Cycles=S.TimeToFirstResponse_Cycles,TimeToResolve_Elapsed=S.TimeToResolve_Elapsed,TimeToResolve_Goal=S.TimeToResolve_Goal,TimeToResolve_Breached=S.TimeToResolve_Breached,TimeToResolve_Cycles=S.TimeToResolve_Cycles,TimeToResolution_Elapsed=S.TimeToResolution_Elapsed,TimeToResolution_Goal=S.TimeToResolution_Goal,TimeToResolution_Breached=S.TimeToResolution_Breached,TimeToResolution_Cycles=S.TimeToResolution_Cycles,TimeToApproveNormalChange_Elapsed=S.TimeToApproveNormalChange_Elapsed,TimeToApproveNormalChange_Goal=S.TimeToApproveNormalChange_Goal,TimeToApproveNormalChange_Breached=S.TimeToApproveNormalChange_Breached,TimeToApproveNormalChange_Cycles=S.TimeToApproveNormalChange_Cycles,ProlongCase_Elapsed=S.ProlongCase_Elapsed,ProlongCase_Goal=S.ProlongCase_Goal,ProlongCase_Breached=S.ProlongCase_Breached,ProlongCase_Cycles=S.ProlongCase_Cycles,TimeToCloseAfterResolution_Elapsed=S.TimeToCloseAfterResolution_Elapsed,TimeToCloseAfterResolution_Goal=S.TimeToCloseAfterResolution_Goal,TimeToCloseAfterResolution_Breached=S.TimeToCloseAfterResolution_Breached,TimeToCloseAfterResolution_Cycles=S.TimeToCloseAfterResolution_Cycles,AppSupEscalation=S.AppSupEscalation WHEN NOT MATCHED THEN INSERT (Project,Key,Summary,Status,Created,Updated,Resolved,Reporter,Assignee,Component,RemedyTicketNumber,Links,{SR_REF_BQ_NAME},SyncTime,TimeToFirstResponse_Elapsed,TimeToFirstResponse_Goal,TimeToFirstResponse_Breached,TimeToFirstResponse_Cycles,TimeToResolve_Elapsed,TimeToResolve_Goal,TimeToResolve_Breached,TimeToResolve_Cycles,TimeToResolution_Elapsed,TimeToResolution_Goal,TimeToResolution_Breached,TimeToResolution_Cycles,TimeToApproveNormalChange_Elapsed,TimeToApproveNormalChange_Goal,TimeToApproveNormalChange_Breached,TimeToApproveNormalChange_Cycles,ProlongCase_Elapsed,ProlongCase_Goal,ProlongCase_Breached,ProlongCase_Cycles,TimeToCloseAfterResolution_Elapsed,TimeToCloseAfterResolution_Goal,TimeToCloseAfterResolution_Breached,TimeToCloseAfterResolution_Cycles,AppSupEscalation) VALUES (S.Project,S.Key,S.Summary,S.Status,S.Created,S.Updated,S.Resolved,S.Reporter,S.Assignee,S.Component,S.RemedyTicketNumber,S.Links,S.{SR_REF_BQ_NAME},S.SyncTime,S.TimeToFirstResponse_Elapsed,S.TimeToFirstResponse_Goal,S.TimeToFirstResponse_Breached,S.TimeToFirstResponse_Cycles,S.TimeToResolve_Elapsed,S.TimeToResolve_Goal,S.TimeToResolve_Breached,S.TimeToResolve_Cycles,S.TimeToResolution_Elapsed,S.TimeToResolution_Goal,S.TimeToResolution_Breached,S.TimeToResolution_Cycles,S.TimeToApproveNormalChange_Elapsed,S.TimeToApproveNormalChange_Goal,S.TimeToApproveNormalChange_Breached,S.TimeToApproveNormalChange_Cycles,S.ProlongCase_Elapsed,S.ProlongCase_Goal,S.ProlongCase_Breached,S.ProlongCase_Cycles,S.TimeToCloseAfterResolution_Elapsed,S.TimeToCloseAfterResolution_Goal,S.TimeToCloseAfterResolution_Breached,S.TimeToCloseAfterResolution_Cycles,S.AppSupEscalation)"""
    try: client.query(merge).result()
    except Exception as e:
        delete_table_quiet(client,dataset,temp); logging.exception(f'Merge failed: {e}'); return False,inserted
    delete_table_quiet(client,dataset,temp); return True,inserted

# ---------------- Logging buffer ----------------
def log_buf(pipeline,run_id,level,msg,fn=None,details=None):
    LOG_BUFFER.append({'Timestamp':datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),'PipelineName':pipeline,'RunID':run_id,'LogLevel':level,'Message':msg,'FunctionName':fn,'Details':details})

def flush_logs(client,dataset,table):
    if not LOG_BUFFER: return
    temp='PipelineLogs_temp_tickets'
    schema=[bigquery.SchemaField(n,t) for n,t in [
        ('Timestamp','TIMESTAMP'),('PipelineName','STRING'),('RunID','STRING'),('LogLevel','STRING'),('Message','STRING'),('FunctionName','STRING'),('Details','STRING')]]
    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp): return
    if not insert_rows_with_retry(client,dataset,temp,LOG_BUFFER,schema): return
    merge=f"MERGE `{dataset}.{table}` T USING (SELECT * FROM `{dataset}.{temp}`) S ON T.Timestamp=S.Timestamp AND T.RunID=S.RunID AND T.Message=S.Message WHEN MATCHED THEN UPDATE SET T.PipelineName=S.PipelineName,T.LogLevel=S.LogLevel,T.FunctionName=S.FunctionName,T.Details=S.Details WHEN NOT MATCHED THEN INSERT (Timestamp,PipelineName,RunID,LogLevel,Message,FunctionName,Details) VALUES (S.Timestamp,S.PipelineName,S.RunID,S.LogLevel,S.Message,S.FunctionName,S.Details)"
    client.query(merge).result(); delete_table_quiet(client,dataset,temp)

# ---------------- Main ----------------
def main():
    cfg=load_config();
    if not cfg: return
    dataset='GSO'; table='JiraTickets'; progress=f'{table}_progress'; log_table='PipelineLogs'; pipeline='jira_tickets'; run_id=str(uuid.uuid4())
    base_days=7; min_start=datetime(2024,7,1); client=bigquery.Client()
    prog_schema=[bigquery.SchemaField(n,t) for n,t in [
        ('WindowStart','TIMESTAMP'),('WindowEnd','TIMESTAMP'),('Status','STRING'),('LastRun','TIMESTAMP'),('Projects','STRING'),('Project','STRING'),('RowCount','INT64')]]
    if not table_exists(client,dataset,progress): create_or_replace_table(client,dataset,progress,prog_schema)
    else:
        for col,ctype in [('Project','STRING'),('RowCount','INT64')]:
            try: client.query(f"ALTER TABLE `{dataset}.{progress}` ADD COLUMN IF NOT EXISTS {col} {ctype}").result()
            except Exception: pass
    default_projects=[
        'GS&O Data Analytics',
        'GS&O Tool Automation',
        'GS&O Knowledge Consolidation',
        'TAC',
        'VOICE - CE',
        'IOT CE',
        'Console Application Support',
        'Console Connect Provisioning',
        'Global Service Delivery Team',
        'Transmission TX-CE',
        'Mobility SMS - CE',
        'Managed Security Services',
        'Vendor Management Escalations'
    ]
    
    parser=argparse.ArgumentParser(); parser.add_argument('--project'); parser.add_argument('--projects'); args,_=parser.parse_known_args()
    if args.projects: req=[p.strip() for p in args.projects.split(',') if p.strip()]; projects=[p for p in default_projects if p in req]
    elif args.project: projects=[p for p in default_projects if p==args.project]
    else: projects=default_projects
    if not projects: return
    user=cfg.get('jira_username') or 'jjkli@consoleconnect.com'; token=cfg.get('jira_api_token')
    if not token: logging.error('jira_api_token missing'); return
    auth=(user,token)
    for proj in projects:
        logging.info(f'Project {proj} start')
        last_completed_start=None
        while True:
            cfgq=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter('p','STRING',proj)])
            ws=None; we=None
            try:
                res=client.query(f"SELECT WindowStart,WindowEnd FROM `{dataset}.{progress}` WHERE Project=@p AND Status NOT IN ('complete','degraded') ORDER BY WindowStart ASC LIMIT 1",job_config=cfgq).result()
                for r in res: ws=r.WindowStart; we=r.WindowEnd; break
            except Exception: pass
            adaptive=base_days
            try:
                hist=list(client.query(f"SELECT RowCount,WindowStart,WindowEnd, IFNULL(Search429,0) Search429, IFNULL(Detail429,0) Detail429 FROM `{dataset}.{progress}` WHERE Project=@p AND Status IN ('complete','degraded') ORDER BY WindowEnd DESC LIMIT 5",job_config=cfgq).result())
                if hist:
                    last=hist[0]; last_count=last.RowCount or 0
                    try: span_hours=max(0.01,(last.WindowEnd-last.WindowStart).total_seconds()/3600.0)
                    except Exception: span_hours=base_days*24
                    base_hours=base_days*24; min_hours=MIN_SHRINK_HOURS; cand_hours=span_hours
                    ls429=getattr(last,'Search429',0) or 0; ld429=getattr(last,'Detail429',0) or 0
                    if (ld429>=RATE_SHRINK_DETAIL_429) or (ls429>=RATE_SHRINK_SEARCH_429):
                        cand_hours=max(min_hours, span_hours*RATE_SHRINK_FACTOR)
                    elif last_count>ADAPT_HIGH_ROWS and span_hours>min_hours: cand_hours=max(min_hours, span_hours/2)
                    elif last_count>ADAPT_MEDIUM_ROWS and span_hours>12: cand_hours=max(12, span_hours/1.5)
                    else:
                        if span_hours<base_hours:
                            recent=hist[:ADAPT_GROW_CONSECUTIVE]
                            if len(recent)==ADAPT_GROW_CONSECUTIVE and all((h.RowCount or 0)<ADAPT_LOW_ROWS for h in recent): cand_hours=min(base_hours, span_hours*2)
                    cand_hours=max(min_hours, min(cand_hours, base_hours)); adaptive=cand_hours/24
            except Exception: pass
            if ws and we:
                cand_end=we
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
                else:
                    ws=min_start
                cand_end=ws+timedelta(days=adaptive)
            ws=ws.replace(tzinfo=None) if getattr(ws,'tzinfo',None) else ws
            now=datetime.utcnow()
            cand_end=cand_end.replace(tzinfo=None) if getattr(cand_end,'tzinfo',None) else cand_end
            we=min(cand_end, now)
            if ws>=now: break
            proj_clause=f'project = "{proj}"' if any(ch in proj for ch in [' ','&']) else f'project = {proj}'
            jql=f"({proj_clause}) AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
            try:
                merge=(
                    f"MERGE `{dataset}.{progress}` T USING (SELECT TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S')}') AS WindowStart, TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS WindowEnd, '{proj}' AS Project) S "
                    "ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project "
                    "WHEN MATCHED THEN UPDATE SET Status='in_progress', LastRun=CURRENT_TIMESTAMP(), Project=S.Project "
                    "WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project) VALUES (S.WindowStart,S.WindowEnd,'in_progress',CURRENT_TIMESTAMP(),S.Project)"
                ); client.query(merge).result()
            except Exception:
                break
            success=False; rc=0
            global SEARCH_429_COUNT, DETAIL_429_COUNT, CURRENT_TICKET_WORKERS, _NO429_STREAK
            SEARCH_429_COUNT=0; DETAIL_429_COUNT=0
            try: success,rc=sync_tickets_window(jql,auth,client,dataset,table,ws,we)
            except Exception as e: log_buf(pipeline,run_id,'ERROR',f'Fatal {proj} {ws}->{we} {e}','main',str(e))
            degraded=False
            if success:
                ratio=DETAIL_429_COUNT/max(1,rc)
                if ratio>FAILURE_RATIO_DEGRADED: degraded=True
            status='degraded' if degraded else ('complete' if success else 'failed')
            upd=(
                f"UPDATE `{dataset}.{progress}` SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc}, Search429={SEARCH_429_COUNT}, Detail429={DETAIL_429_COUNT} WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND Status!='complete'"
            ); client.query(upd).result()
            if status in ('complete','degraded'):
                last_completed_start=ws
                if (SEARCH_429_COUNT>0 or DETAIL_429_COUNT>0):
                    CURRENT_TICKET_WORKERS=max(TICKET_MIN_WORKERS,int(CURRENT_TICKET_WORKERS*TICKET_SCALE_DOWN_FACTOR)); _NO429_STREAK=0
                else:
                    _NO429_STREAK+=1
                    if _NO429_STREAK>=TICKET_SCALE_UP_NO429_WINDOWS and CURRENT_TICKET_WORKERS<TICKET_MAX_WORKERS:
                        CURRENT_TICKET_WORKERS=min(TICKET_MAX_WORKERS,max(CURRENT_TICKET_WORKERS+1,int(CURRENT_TICKET_WORKERS*TICKET_SCALE_UP_FACTOR))); _NO429_STREAK=0
            if not success:
                try: span_hours=(we-ws).total_seconds()/3600.0
                except Exception: span_hours=0
                if span_hours>(MIN_SHRINK_HOURS+0.05):
                    new_span=max(MIN_SHRINK_HOURS,span_hours*RATE_SHRINK_FACTOR); new_end=ws+timedelta(hours=new_span)
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET WindowEnd=TIMESTAMP('{new_end.strftime('%Y-%m-%d %H:%M:%S')}'), Status='failed' WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING)"
                        ).result();
                        continue
                    except Exception: break
                else:
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET Status='degraded' WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND Status='failed'"
                        ).result()
                    except Exception: pass
                    break
        log_buf(pipeline,run_id,'INFO',f'Project {proj} finished','main')
    log_buf(pipeline,run_id,'INFO','Tickets pipeline finished','main'); flush_logs(client,dataset,log_table)

if __name__=='__main__':
    main()
