"""Unified comments initial sync pipeline.
Enhancements added:
 - Robust multi-location Jira config search (env JSON -> script dir -> repo root -> hourly jira_tickets config)
 - Environment variable overrides (JIRA_USERNAME / JIRA_API_TOKEN)
 - Token length warning for suspicious short tokens
 - Project visibility preflight (maxResults=0) to fail fast on bad credentials
 - Automatic GOOGLE_APPLICATION_CREDENTIALS discovery (service-account.json / jira-bigquery-key.json at repo root)
 - Repository root added to sys.path for reliable shared/ imports
"""
import argparse, json, logging, time, uuid, requests, random, threading, os, sys, pathlib
# Ensure repository root is on sys.path for importing local helper modules
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
"""Path setup so 'shared' package imports work when executed from subfolder / container workdir."""
_script_dir = pathlib.Path(__file__).resolve().parent
_root_dir = _script_dir.parent.parent  # InitialSync/ -> repo root
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

# Auto-set GOOGLE_APPLICATION_CREDENTIALS if not already set and a known key exists
if 'GOOGLE_APPLICATION_CREDENTIALS' not in os.environ:
    for cand in ('service-account.json','jira-bigquery-key.json', 'credentials.json'):
        p = _repo_root / 'shared' / cand
        if p.exists():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(p)
            break

from shared.pipeline_runs_logger import log_pipeline_run

DEBUG=False
# Allow runtime log level override via env (LOG_LEVEL=DEBUG|INFO|WARNING|ERROR)
_env_level = os.environ.get('LOG_LEVEL', None)
_level = getattr(logging, _env_level.upper(), None) if _env_level else (logging.DEBUG if DEBUG else logging.INFO)
logging.basicConfig(level=_level, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Comments initial sync starting up")

# Embedded default project list for deterministic runs; ensures Customer Success Management included
default_projects = [
    'GS&O Data Analytics',
    'GS&O Tool Automation',
    'GS&O Knowledge Consolidation',
    'Google Contact Center AI Solution',
    'TAC',
    'VOICE - CE',
    'IOT CE',
    'Console Application Support',
    'Console Connect Provisioning',
    'Global Service Delivery Team',
    'Transmission TX-CE',
    'Mobility SMS - CE',
    'Managed Security Services',
    'Sherbet',
    'Customer Success Management',
    'Operational Case Reviews',
    'QMS Documentation'
]

# Adaptive thresholds
ADAPT_HIGH_ROWS=50000
ADAPT_MEDIUM_ROWS=15000
ADAPT_LOW_ROWS=2000
ADAPT_GROW_CONSECUTIVE=3
MIN_SHRINK_HOURS=6
MAX_GROW_DAYS=7

OVERLAP_MINUTES=60
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

MIN_WINDOW_MINUTES=30         # minimum window size in minutes to prevent tiny windows

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
PIPELINE_NAME='jira_comments_initialsync'

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
    """Load Jira configuration with layered fallback.
    Order:
      1. Env var JIRA_CONFIG_JSON (JSON string)
      2. Local config (same directory)
      3. Repo root config.json
      4. Hourly jira_tickets config.json (reuse known-good long token)
    Returns dict or None.
    """
    # 1. Env JSON
    env_cfg = os.environ.get('JIRA_CONFIG_JSON')
    if env_cfg:
        try:
            data = json.loads(env_cfg)
            logging.info('Loaded Jira config from JIRA_CONFIG_JSON env var')
            return data
        except Exception:
            logging.warning('Failed to parse JIRA_CONFIG_JSON env var')
    candidates = []
    try:
        candidates.append(str(_script_dir / 'config.json'))
        candidates.append(str(_root_dir / 'config.json'))
        candidates.append(str(_root_dir / 'Hourly' / 'jira_tickets' / 'config.json'))
    except Exception:
        pass
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            token = data.get('jira_api_token')
            if token and len(token) < 40:
                logging.warning(f'Loaded very short jira_api_token (len={len(token)}) from {path}; may be invalid')
            else:
                logging.info(f'Loaded Jira config from {path} (token length {len(token) if token else 0})')
            return data
        except Exception as e:
            logging.debug(f'Could not load config from {path}: {e}')
    logging.error('No Jira config found in expected locations')
    return None

def preflight_validate_project(auth, project_name, base_url='https://consoleconnect.atlassian.net'):
    """Run lightweight maxResults=0 search to confirm visibility to project.
    Returns (ok, status_code, message)."""
    # Use tenant-accepted GET /rest/api/3/search/jql with query params
    search_url = f"{base_url}/rest/api/3/search/jql"
    test_jql = f'project = "{project_name}"'
    params = {'jql': test_jql, 'startAt': 0, 'maxResults': 1, 'fields': 'key'}
    headers = {'Accept': 'application/json'}
    try:
        r = requests.get(search_url, headers=headers, auth=auth, params=params, timeout=30)
        if r.status_code == 200:
            return True, r.status_code, 'ok'
        snippet = (r.text or '')[:300].replace('\n', ' ')
        if r.status_code in (400, 404):
            return False, r.status_code, f'Not visible/invalid: {snippet}'
        if r.status_code == 401:
            return False, r.status_code, 'Unauthorized'
        if r.status_code == 403:
            return False, r.status_code, 'Forbidden'
        return False, r.status_code, snippet
    except Exception as e:
        return False, -1, f'Exception: {e}'

def load_projects_from_file(defaults):
    """Load project names for Docker/local.
    Order: env JQL_FILE -> ../JQL.txt -> /app/InitialSync/JQL.txt -> /config/JQL.txt -> /data/JQL.txt.
    Supports comments: lines starting with #, //, --, and inline markers after a space ( #, //, -- ).
    Blank lines ignored. Returns list of cleaned project names in file order (first match wins).
    """
    # External JQL / project-list loading removed for deterministic behavior.
    # Always return the provided defaults so pipeline uses embedded list only.
    return defaults


def to_utc_aware(dt):
    if dt is None: return None
    if getattr(dt, 'tzinfo', None):
        try:
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt.replace(tzinfo=timezone.utc)
    else:
        return dt.replace(tzinfo=timezone.utc)

def convert_ts(ts):
    if not ts: return None
    fmts=['%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S']
    for fmt in fmts:
        try:
            # Parse the timestamp according to format. Some formats use a literal 'Z' (UTC)
            dt = datetime.strptime(ts, fmt)
            # If format contained a literal Z (ISO UTC), set tzinfo to UTC
            if fmt.endswith('Z') and '%z' not in fmt:
                dt = dt.replace(tzinfo=timezone.utc)
            # If dt has tzinfo, convert to UTC and produce a naive UTC datetime for storage/comparison
            if getattr(dt, 'tzinfo', None) is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
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
            msg=str(e)
            if 'not found' in msg.lower():
                logging.warning(f"Temp table missing {dataset}.{table}; recreating (attempt {attempt+1})")
                if not create_or_replace_table(client,dataset,table,schema) or not wait_for_table(client,dataset,table): return False
                # brief pause to avoid post-DDL streaming race
                time.sleep(2)
            else:
                logging.exception(f'Insert exception: {e}')
        if attempt<retries-1: time.sleep(delay)
    return False

def delete_table_quiet(client,dataset,table):
    try: client.delete_table(f"{dataset}.{table}")
    except Exception: pass

def fetch_issues_page(search_url,auth,headers,jql,start_at,max_results):
    """Use GET /rest/api/3/search/jql with query params to fetch issues."""
    global SEARCH_429_COUNT
    params = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': 'key'}
    for attempt in range(5):
        try:
            logging.debug(f"Searching issues startAt={start_at} maxResults={max_results} attempt={attempt+1}/5")
            RATE_LIMITER.take()
            r = requests.get(search_url, headers=headers, auth=auth, params=params, timeout=120)
            if r.status_code == 429:
                SEARCH_429_COUNT += 1
                ra = int(r.headers.get('Retry-After', 30) or 30)
                logging.warning(f"429 search attempt {attempt+1}/5 startAt={start_at}; sleeping {ra:.1f}s")
                time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                continue
            if r.status_code != 200:
                snippet = (r.text or '')[:300].replace('\n',' ')
                logging.warning(f'Jira search non-200 status={r.status_code} attempt={attempt+1} startAt={start_at} resp_snippet="{snippet}"')
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            logging.warning(f"Search timeout attempt {attempt+1}/5 startAt={start_at}")
            time.sleep(15)
        except requests.RequestException as e:
            try:
                status = getattr(e.response, 'status_code', None)
            except Exception:
                status = None
            logging.error(f'Error searching issues on attempt {attempt+1}/5: {e} status={status}')
            if status == 429:
                SEARCH_429_COUNT += 1
                time.sleep(5*(attempt+1))
                continue
            if attempt < 4:
                time.sleep(10)
                continue
            return None
    return None

def fetch_comments_for_issue(base_url,issue_key,auth):
    global DETAIL_429_COUNT
    url=f"{base_url}/rest/api/2/issue/{issue_key}/comment"; start=0; size=100; out=[]; attempts=0
    while True:
        try:
            RATE_LIMITER.take(); r=requests.get(url,auth=auth,params={'startAt':start,'maxResults':size},timeout=180)
            if r.status_code==429:
                DETAIL_429_COUNT+=1; ra=int(r.headers.get('Retry-After',10)); sleep_for=ra+random.uniform(0,JITTER_MAX_SECONDS)
                logging.warning(f"429 comments {issue_key} startAt={start}; sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for); continue
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
    def _body_to_string(body):
        """Normalize Jira comment body to a string.
        - If already a string, return it.
        - If ADF (dict with 'content'), try to extract plain text.
        - Otherwise fallback to JSON-dumped string.
        """
        if body is None:
            return None
        if isinstance(body, str):
            return body
        try:
            # Try Atlassian Document Format (ADF) extraction
            if isinstance(body, dict) and 'content' in body:
                parts = []
                def walk(node):
                    if node is None:
                        return
                    if isinstance(node, str):
                        parts.append(node)
                        return
                    if isinstance(node, dict):
                        if 'text' in node and isinstance(node['text'], str):
                            parts.append(node['text'])
                        for k in ('content','content_list'):
                            if k in node and isinstance(node[k], list):
                                for child in node[k]:
                                    walk(child)
                        return
                    if isinstance(node, list):
                        for item in node:
                            walk(item)
                walk(body.get('content'))
                if parts:
                    return ' '.join(parts)
        except Exception:
            pass
        try:
            return json.dumps(body, ensure_ascii=False)
        except Exception:
            return str(body)
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
                'Created': created,'Updated': updated,'Body': _body_to_string(c.get('body')),'Visibility_Type': vis.get('type'),'Visibility_Value': vis.get('value'),'SyncTime': now_str,
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
    # Use the GET-based search endpoint preferred by our Jira tenant
    search_url=f"{base_url}/rest/api/3/search/jql"; headers={'Accept':'application/json'}
    start=0; max_results=100; total=float('inf'); buf=[]; batch=1000; inserted=0
    while start<total:
        data=fetch_issues_page(search_url,auth,headers,jql,start,max_results)
        if data is None:
            logging.error("Issue search failed permanently; aborting window.")
            delete_table_quiet(client,dataset,temp); return False,inserted
        issues=data.get('issues',[]); total=data.get('total',0)
        try:
            logging.debug(f"Search returned issues={len(issues)} total={total} startAt={start}")
        except Exception:
            pass
        if not issues: break
        keys=[i.get('key') for i in issues if i.get('key')]
        cmap=fetch_comments_batch(base_url,keys,auth)
        total_comments = sum(len(v) for v in cmap.values())
        nonzero_items = [(k,len(v)) for k,v in cmap.items() if v]
        logging.debug(f"Fetched comments for {len(keys)} keys; non-empty maps={len(nonzero_items)}")
        if nonzero_items:
            sample = nonzero_items[:20]
            logging.info(f"Comments fetched total={total_comments} non_empty_keys={len(nonzero_items)} sample={sample}")
        rows_page = 0
        for row in generate_rows(issues,cmap,ws,we):
            buf.append(row)
            rows_page += 1
            if len(buf)>=batch:
                if not insert_rows_with_retry(client,dataset,temp,buf,schema): delete_table_quiet(client,dataset,temp); return False,inserted
                inserted+=len(buf); buf=[]
        logging.debug(f"Generated rows this page={rows_page}; total inserted so far={inserted}")
        if buf:
            if not insert_rows_with_retry(client,dataset,temp,buf,schema): delete_table_quiet(client,dataset,temp); return False,inserted
            inserted+=len(buf); buf=[]
        prev_start = start
        start+=len(issues)
        if start == prev_start:
            logging.warning("Pagination made no progress (start unchanged); breaking to avoid loop")
            break
        logging.debug(f"Advancing start from {prev_start} by {len(issues)} -> {start} of {total}")
        time.sleep(1)
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

# Alias aligned with changelog script naming
def log_to_bigquery_buffer(pipeline, run_id, level, message, function_name=None, details=None):
    # Legacy buffer logging retained as no-op alias; PipelineRuns logger is used instead.
    return

def flush_logs(client,dataset,table):
    # Legacy PipelineLogs flush disabled (no-op)
    return

def main():
    cfg=load_config();
    if not cfg: return
    dataset='GSO'; table='JiraComments'; progress=f'{table}_progress'; pipeline='jira_comments'; run_id=str(uuid.uuid4()); base_days=7
    min_start=datetime(2024,7,1); client=bigquery.Client(); now=datetime.utcnow()
    run_started = datetime.utcnow()  # Track overall pipeline start time
    prog_schema=[bigquery.SchemaField(n,t) for n,t in [ ('WindowStart','TIMESTAMP'),('WindowEnd','TIMESTAMP'),('Status','STRING'),('LastRun','TIMESTAMP'),('Projects','STRING'),('Project','STRING'),('RowCount','INT64'),('Search429','INT64'),('Detail429','INT64')]]
    if not table_exists(client,dataset,progress): create_or_replace_table(client,dataset,progress,prog_schema)
    else:
        for col,ctype in [('Project','STRING'),('RowCount','INT64'),('Search429','INT64'),('Detail429','INT64')]:
            try: client.query(f"ALTER TABLE `{dataset}.{progress}` ADD COLUMN IF NOT EXISTS {col} {ctype}").result()
            except Exception: pass
    default_projects = [
    'GS&O Data Analytics',
    'GS&O Tool Automation',
    'GS&O Knowledge Consolidation',
    'Google Contact Center AI Solution',
    'TAC',
    'VOICE - CE',
    'IOT CE',
    'Console Application Support',
    'Console Connect Provisioning',
    'Global Service Delivery Team',
    'Transmission TX-CE',
    'Mobility SMS - CE',
    'Managed Security Services',
    'Sherbet',
    'Customer Success Management'
    ]
    # External file override removed: always use embedded defaults
    default_projects = load_projects_from_file(default_projects)
    projects = default_projects
    logging.info('Using embedded default_projects for comments pipeline; CLI and ENV overrides ignored')
    user = os.environ.get('JIRA_USERNAME') or cfg.get('jira_username') or 'jjkli@consoleconnect.com'
    token = os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
    if not token:
        logging.error('jira_api_token missing'); return
    auth=(user,token); base_url='https://consoleconnect.atlassian.net'
    for proj in projects:
        logging.info(f"Starting backfill for project {proj}")
        ok, sc, msg = preflight_validate_project(auth, proj, base_url)
        if not ok:
            logging.error(f'Preflight failed for project "{proj}" status={sc} detail={msg}; skipping')
            log_pipeline_run(None, pipeline_name=PIPELINE_NAME, run_id=run_id, level='ERROR', message=f'Preflight failed {proj}: {msg}', status='ERROR')
            continue
        log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message=f"Starting backfill for project {proj}", status="RUNNING")
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
                    now_naive = now.replace(tzinfo=None)
                    # If there have been no updates since the last recorded WindowEnd (within the overlap window),
                    # skip this project to avoid creating tiny windows (seconds/minutes) and move on.
                    if (now_naive - latest_naive) <= overlap:
                        logging.info(f"No new updates for {proj} since last window end {latest_naive}; skipping")
                        break
                    last_completed_naive=last_completed_start.replace(tzinfo=None) if (last_completed_start and getattr(last_completed_start,'tzinfo',None)) else last_completed_start
                    # Start just before the last recorded end to keep a small overlap, but avoid reprocessing too-old ranges
                    cand_start=latest_naive-overlap
                    if last_completed_naive and cand_start<=last_completed_naive:
                        cand_start=latest_naive
                    if last_completed_naive and (latest_naive-last_completed_naive)<=overlap*2:
                        cand_start=latest_naive
                    if cand_start<min_start: cand_start=min_start
                    ws=cand_start
                else: ws=min_start
                cand=ws+timedelta(days=adaptive)
            ws_naive=ws.replace(tzinfo=None) if getattr(ws,'tzinfo',None) else ws
            now_naive=now.replace(tzinfo=None)
            cand_naive=cand.replace(tzinfo=None) if getattr(cand,'tzinfo',None) else cand
            we=min(cand_naive,now_naive)

            # Check if window is too small (less than minimum threshold)
            window_span_minutes = (we - ws_naive).total_seconds() / 60
            if window_span_minutes < MIN_WINDOW_MINUTES:
                logging.info(f"Window for {proj} is too small ({window_span_minutes:.1f} minutes < {MIN_WINDOW_MINUTES} minutes); moving to next project")
                break

            # Clamp oversized existing window spans to base_days (align with changelog behavior)
            try:
                span_days=(we-ws_naive).days+((we-ws_naive).seconds/86400)
            except Exception:
                span_days=base_days
            if span_days>base_days+0.01:
                try:
                    new_end=ws_naive+timedelta(days=base_days)
                    client.query(
                        f"UPDATE `{dataset}.{progress}` SET WindowEnd=TIMESTAMP('{new_end}') WHERE Project='{proj}' AND Status!='complete' "
                        f"AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S')}') AS STRING)"
                    ).result();
                    logging.info(f"Clamped oversized window for {proj} from span {span_days:.2f}d to {base_days}d; re-evaluating")
                    continue
                except Exception:
                    logging.warning(f"Failed to clamp oversized window for {proj}; aborting project")
                    break
            if ws_naive>=now_naive: break
            proj_clause=f'project = "{proj}"' if (' ' in proj or '&' in proj) else f'project = {proj}'
            jql=f"({proj_clause}) AND updated >= \"{ws_naive.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
            try:
                merge=(
                    f"MERGE `{dataset}.{progress}` T USING (SELECT TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS WindowStart, TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS WindowEnd, '{proj}' AS Project) S "
                    "ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project "
                    "WHEN MATCHED THEN UPDATE SET Status='in_progress', LastRun=CURRENT_TIMESTAMP(), Project=S.Project "
                    "WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project) VALUES (S.WindowStart,S.WindowEnd,'in_progress',CURRENT_TIMESTAMP(),S.Project)"
                ); client.query(merge).result(); logging.info(f"Project {proj} window {ws_naive} -> {we} marked in_progress")
                log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message="Window in_progress", status="RUNNING", window_start=ws_naive.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))
            except Exception:
                break
            SUCCESS=False; rc=0
            window_start_time = datetime.utcnow()  # Track window processing start time
            global SEARCH_429_COUNT, DETAIL_429_COUNT, CURRENT_DETAIL_WORKERS, _NO429_STREAK
            SEARCH_429_COUNT=0; DETAIL_429_COUNT=0
            try: SUCCESS,rc=sync_window(base_url,jql,auth,client,dataset,table,ws_naive,we)
            except Exception as e:
                logging.exception(f"Window sync fatal error for {proj}: {e}")
                log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="ERROR", message=f"Fatal {proj} {ws_naive}->{we} {e}", status="ERROR")
            degraded=False
            if SUCCESS:
                ratio=DETAIL_429_COUNT/max(1,rc)
                if ratio>FAILURE_RATIO_DEGRADED: degraded=True
            status='degraded' if degraded else ('complete' if SUCCESS else 'failed')
            window_end_time = datetime.utcnow()
            window_duration_seconds = (window_end_time - window_start_time).total_seconds()
            upd=(
                f"UPDATE `{dataset}.{progress}` SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc}, Search429={SEARCH_429_COUNT}, Detail429={DETAIL_429_COUNT} "
                f"WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND Status!='complete'"
            ); client.query(upd).result()
            logging.info(f"Project {proj} window {ws_naive}->{we} {status} rows={rc} 429_search={SEARCH_429_COUNT} 429_detail={DETAIL_429_COUNT}")
            log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level=("INFO" if SUCCESS else "ERROR"), message=f"Window {status} {proj}", status=("SUCCESS" if SUCCESS else "ERROR"), window_start=ws_naive.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'), rows_merged=int(rc), duration_seconds=window_duration_seconds)
            if status in ('complete','degraded'):
                last_completed_start=ws_naive
                if (SEARCH_429_COUNT>0 or DETAIL_429_COUNT>0):
                    CURRENT_DETAIL_WORKERS=max(DETAIL_MIN_WORKERS,int(CURRENT_DETAIL_WORKERS*DETAIL_SCALE_DOWN_FACTOR)); _NO429_STREAK=0
                    logging.info(f"Scaling down comment workers to {CURRENT_DETAIL_WORKERS} due to 429s")
                else:
                    _NO429_STREAK+=1
                    if _NO429_STREAK>=DETAIL_SCALE_UP_NO429_WINDOWS and CURRENT_DETAIL_WORKERS<DETAIL_MAX_WORKERS:
                        CURRENT_DETAIL_WORKERS=min(DETAIL_MAX_WORKERS,max(CURRENT_DETAIL_WORKERS+1,int(CURRENT_DETAIL_WORKERS*DETAIL_SCALE_UP_FACTOR))); _NO429_STREAK=0
                        logging.info(f"Scaling up comment workers to {CURRENT_DETAIL_WORKERS} (no 429 streak)")
            # Legacy flush disabled
            if not SUCCESS:
                try: span_hours=(we-ws_naive).total_seconds()/3600.0
                except Exception: span_hours=0
                if span_hours>(MIN_SHRINK_HOURS+0.05):
                    new_span=max(MIN_SHRINK_HOURS,span_hours*RATE_SHRINK_FACTOR); new_end=ws_naive+timedelta(hours=new_span)
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET WindowEnd=TIMESTAMP('{new_end.strftime('%Y-%m-%d %H:%M:%S.%f')}'), Status='failed' WHERE Project='{proj}' "
                            f"AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING)"
                        ).result();
                        logging.info(f"Shrinking failed window for {proj} from {span_hours:.2f}h -> {new_span:.2f}h; will retry")
                        continue
                    except Exception: break
                else:
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET Status='degraded' WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND Status='failed'"
                        ).result()
                    except Exception: pass
                    break
    run_ended = datetime.utcnow()
    duration_seconds = (run_ended - run_started).total_seconds()
    log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message="Comments pipeline finished", status="SUCCESS", duration_seconds=duration_seconds)

if __name__=='__main__':
    main()
