"""Jira Tickets Initial Sync (Refactored)
Per-project adaptive window backfill (base 7d, shrink to 6h, regrow) aligned with changelog & comments pipelines.
Temp staging + MERGE, progress ledger (Project, RowCount), buffered logging, SLA metrics extraction.
"""
import json, logging, time, uuid, requests, argparse, random, threading, os, re, sys, pathlib
# Ensure repository root is on sys.path for importing local helper modules
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Ensure repository root (sibling of InitialSync/) is on sys.path so we can import 'shared'
_script_dir = pathlib.Path(__file__).resolve().parent
_root_dir = _script_dir.parent.parent  # go up from jira_tickets_initialsync/ to InitialSync/ then to repo root
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

# Auto-set GOOGLE_APPLICATION_CREDENTIALS if not provided and common key files exist in repo root
if 'GOOGLE_APPLICATION_CREDENTIALS' not in os.environ:
    for candidate in ['service-account.json','jira-bigquery-key.json']:
        cand_path = _root_dir / candidate
        if cand_path.exists():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(cand_path)
            break
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
# Attempt to import shared logger; provide local fallback if shared/ not packaged in Docker context
try:
    from shared.pipeline_runs_logger import log_pipeline_run  # type: ignore
except ModuleNotFoundError:
    # Fallback: try sibling file (we may vendor a copy named pipeline_runs_logger.py)
    try:
        from pipeline_runs_logger import log_pipeline_run  # type: ignore
    except ModuleNotFoundError:
        # Final fallback: lightweight no-op implementation to keep pipeline running
        def log_pipeline_run(client, *, pipeline_name: str, run_id: str, level: str, message: str, status: str, **kwargs):  # type: ignore
            logging.log(getattr(logging, level.upper(), logging.INFO), f"[fallback-log] {pipeline_name} {status} {message}")
            return

DEBUG=False
# Allow runtime log level override via env (LOG_LEVEL=DEBUG|INFO|WARNING|ERROR)
_env_level = os.environ.get('LOG_LEVEL', None)
_level = getattr(logging, _env_level.upper(), None) if _env_level else (logging.DEBUG if DEBUG else logging.INFO)
logging.basicConfig(
    level=_level if isinstance(_level, int) else (logging.DEBUG if DEBUG else logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
LOG_BUFFER=[]
PIPELINE_NAME='jira_tickets_initialsync'

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

# Progress window hygiene: treat very tiny backlog windows as noise
MIN_PROGRESS_WINDOW_SEC=600  # 10 minutes

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

# Track tables we've already ensured schema for during this process to avoid repeated DDL
SCHEMA_ENSURED=set()

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

# Fields to request from Jira search to avoid per-issue detail calls
FIELDS_FOR_SEARCH=[
    'key','issuetype','summary','status','priority','resolution','created','updated','resolutiondate','project','reporter','assignee','components','issuelinks',
    SR_REF_JIRA_ID, ESCALATION_FIELD,
    # SLA custom fields
    *list(SLA_FIELDS_MAP.values())
]

# ---------------- Utilities ----------------
def load_config():
    """Load Jira config searching multiple fallback locations.
    Order:
      1. Env JSON (JIRA_CONFIG_JSON)
      2. Local folder config (same dir as this script)
      3. Repo root config.json
      4. Hourly jira_tickets config (to reuse existing token) as fallback
    """
    # 1. Env override
    env_cfg = os.environ.get('JIRA_CONFIG_JSON')
    if env_cfg:
        try:
            data = json.loads(env_cfg)
            return data
        except Exception:
            logging.warning('Failed to parse JIRA_CONFIG_JSON env var')
    candidates = []
    try:
        script_dir = os.path.dirname(__file__)
        repo_root = _root_dir  # already defined earlier
        candidates.append(os.path.join(script_dir, 'config.json'))
        candidates.append(os.path.join(str(repo_root), 'config.json'))
        # Hourly ticket config (where working long token likely lives)
        candidates.append(os.path.join(str(repo_root), 'Hourly', 'jira_tickets', 'config.json'))
    except Exception:
        pass
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                token = data.get('jira_api_token')
                if token and len(token) < 40:
                    logging.warning(f'Loaded a very short jira_api_token (len={len(token)}) from {path}; this may be invalid.')
                else:
                    logging.info(f'Loaded jira config from {path} (token length {len(token) if token else 0})')
                return data
        except Exception as e:
            logging.debug(f'Could not load config from {path}: {e}')
    logging.error('No config.json found in expected locations');
    return None

def load_projects_from_file(defaults):
    """Load project names for Docker/local with comment support.
    Resolution order: env JQL_FILE -> ../JQL.txt -> /app/InitialSync/JQL.txt -> /config/JQL.txt -> /data/JQL.txt.
    Ignore lines starting with #, //, -- and trim inline comments after space + marker.
    """
    candidates=[]
    env_path=os.environ.get('JQL_FILE') or os.environ.get('PROJECTS_FILE')
    if env_path:
        candidates.append(env_path)
    script_dir=os.path.dirname(__file__)
    # Parent InitialSync/JQL.txt (not available inside image if build context is this folder only)
    candidates.append(os.path.normpath(os.path.join(script_dir,'..','JQL.txt')))
    # Local folder JQL.txt (add this so dropping a file beside main.py works in Docker)
    candidates.append(os.path.join(script_dir,'JQL.txt'))
    # Common in-container fallback locations (mount or multi-folder copy patterns)
    candidates.extend(['/app/JQL.txt','/app/InitialSync/JQL.txt','/config/JQL.txt','/data/JQL.txt'])
    comment_starts = ('#','//','--')
    inline_markers = [' #',' //',' -- ']
    found_source = None
    for p in candidates:
        try:
            if not p or not os.path.exists(p):
                logging.debug(f'Project list candidate not found: {p}')
                continue
            with open(p,'r',encoding='utf-8') as f:
                raw_lines=f.readlines()
            items=[]
            for ln in raw_lines:
                ln = ln.rstrip('\r\n')
                stripped = ln.strip()
                if not stripped:
                    continue
                if stripped.startswith(comment_starts):
                    continue
                work = stripped
                for marker in inline_markers:
                    idx = work.find(marker)
                    if idx > 0:
                        work = work[:idx].strip()
                        break
                if work:
                    items.append(work)
            if items:
                logging.info(f'Loaded project list from {p} ({len(items)})')
                found_source = p
                return items
        except Exception as ie:
            logging.debug(f'Project list read failed for {p}: {ie}')
    if not found_source:
        logging.warning('No JQL project file found; using embedded default project list (set SINGLE_PROJECT / mount JQL.txt to override).')
    return defaults


def to_utc_aware(dt):
    """Return a timezone-aware datetime in UTC for input dt which may be naive or aware."""
    if dt is None: return None
    if getattr(dt, 'tzinfo', None):
        try:
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt.replace(tzinfo=timezone.utc)
    else:
        # assume naive times are UTC
        return dt.replace(tzinfo=timezone.utc)


def parse_test_window_env():
    """Parse TEST_WINDOW_START and TEST_WINDOW_END env vars (ISO-like). Return tuple (ws,we) as UTC-aware datetimes or (None,None).
    Supported formats: ISO 8601 with optional 'Z' or timezone (eg 2025-08-01T00:00:00Z or 2025-08-01T00:00:00+00:00)
    Also accepts 'YYYY-MM-DD HH:MM' and 'YYYY/MM/DD HH:MM'. Times without tz are assumed UTC.
    """
    s = os.environ.get('TEST_WINDOW_START')
    e = os.environ.get('TEST_WINDOW_END')
    if not s or not e:
        return None, None
    def _parse(x):
        if not x: return None
        x = x.strip()
        # normalize Z -> +00:00 for fromisoformat
        if x.endswith('Z'):
            x = x[:-1] + '+00:00'
        # try iso first
        try:
            dt = datetime.fromisoformat(x)
            return to_utc_aware(dt)
        except Exception:
            pass
        # try common formats used in this repo
        for fmt in ('%Y-%m-%d %H:%M','%Y/%m/%d %H:%M','%Y-%m-%d %H:%M:%S','%Y/%m/%d %H:%M:%S'):
            try:
                dt = datetime.strptime(x, fmt)
                return to_utc_aware(dt)
            except Exception:
                continue
        return None
    try:
        ws = _parse(s); we = _parse(e)
        if ws and we and ws < we:
            logging.info(f'Using TEST_WINDOW_START/END override: {ws} -> {we}')
            return ws, we
    except Exception:
        pass
    logging.warning('Invalid TEST_WINDOW_START/END environment variables; ignoring')
    return None, None

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

def extract_issue_links(issuelinks):
    """Extract a readable list of linked issue keys with optional status, e.g. "PROJ-123 [Done], ABC-9"."""
    if not issuelinks or not isinstance(issuelinks, list):
        return None
    links=[]
    def status_name(issue):
        if not issue: return None
        st=issue.get('fields',{}).get('status',{})
        return st.get('name')
    for link in issuelinks:
        for direction in ('outwardIssue','inwardIssue'):
            iss=link.get(direction)
            if not iss: continue
            k=iss.get('key'); sn=status_name(iss)
            if k:
                links.append(f"{k} [{sn}]" if sn else k)
    return ', '.join(links) if links else None

def extract_incident_numbers(text):
    """Extract all incident numbers like INC followed by 9+ digits from the provided text."""
    if not text: return []
    if isinstance(text, list):
        text=' | '.join([str(t) for t in text if t])
    return re.findall(r'INC\d{9,}', str(text))

# ---------------- BigQuery helpers ----------------
def table_exists(client,dataset,table):
    try: client.get_table(f"{dataset}.{table}"); return True
    except Exception: return False

def _bq_type_with_mode(c: bigquery.SchemaField) -> str:
    """Render BigQuery DDL type for a schema field.
    - REPEATED -> ARRAY<type>
    - REQUIRED -> keep base type (we avoid NOT NULL in DDL to stay safe on ALTERs without defaults)
    - NULLABLE -> base type
    """
    base = c.field_type
    mode = (c.mode or '').upper()
    if mode == 'REPEATED':
        return f"ARRAY<{base}>"
    return base

def create_or_replace_table(client,dataset,table,schema):
    try:
        cols=','.join(f'`{c.name}` {_bq_type_with_mode(c)}' for c in schema)
        client.query(f"CREATE OR REPLACE TABLE `{dataset}.{table}` ({cols})").result(); return True
    except Exception as e:
        logging.exception(f'Create/replace {dataset}.{table} failed: {e}'); return False

def wait_for_table(client,dataset,table,retries=10,delay=2):
    for _ in range(retries):
        if table_exists(client,dataset,table): return True
        time.sleep(delay)
    return False

def ensure_table_columns(client,dataset,table,schema):
    """Add missing columns to an existing table to match the provided schema.
    Uses ARRAY<T> for repeated fields; leaves nullability default for safety.
    """
    try:
        # Fetch existing schema to avoid issuing unnecessary DDL per column per window
        tbl = client.get_table(f"{dataset}.{table}")
        existing = {c.name for c in tbl.schema}
        missing = [c for c in schema if c.name not in existing]
        for c in missing:
            ddl_type = _bq_type_with_mode(c)
            client.query(
                f"ALTER TABLE `{dataset}.{table}` ADD COLUMN IF NOT EXISTS `{c.name}` {ddl_type}"
            ).result()
        return True
    except Exception as e:
        logging.warning(f'ensure_table_columns failed for {dataset}.{table}: {e}')
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
SEARCH_URL=f'{BASE_URL}/rest/api/3/search/jql'

def fetch_issues_page(auth,jql,start_at,max_results):
    """Fetch a page of issues using GET /rest/api/3/search/jql with query params.
    Returns parsed JSON or None on failure."""
    global SEARCH_429_COUNT
    headers={'Accept':'application/json'}
    params = {
        'jql': jql,
        'startAt': start_at,
        'maxResults': max_results,
        # send fields as comma separated list
        'fields': ','.join(FIELDS_FOR_SEARCH)
    }
    for attempt in range(5):
        try:
            RATE_LIMITER.take()
            r = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params, timeout=120)
            if r.status_code == 429:
                SEARCH_429_COUNT += 1
                ra = int(r.headers.get('Retry-After', 30) or 30)
                logging.warning(f'429 search startAt={start_at}; sleeping {ra:.1f}s')
                time.sleep(ra + random.random()*JITTER_MAX_SECONDS)
                continue
            if r.status_code != 200:
                snippet = (r.text or '')[:300].replace('\n',' ')
                logging.warning(f'Jira search non-200 status={r.status_code} attempt={attempt+1} startAt={start_at} resp_snippet="{snippet}"')
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            time.sleep(15)
        except requests.RequestException as re:
            try:
                status = getattr(re.response, 'status_code', None)
            except Exception:
                status = None
            logging.error(f'Error searching issues on attempt {attempt+1}/5: {re} status={status}')
            if status == 429:
                SEARCH_429_COUNT += 1
                time.sleep(5*(attempt+1))
                continue
            if attempt < 4:
                time.sleep(10)
                continue
            return None
    return None

def preflight_validate_project(auth, project_name):
    """Run a lightweight maxResults=0 search to verify the authenticated user can see the project.
    Returns (ok, status_code, message)."""
    test_jql = f'project = "{project_name}"'
    params = {'jql': test_jql, 'startAt': 0, 'maxResults': 1, 'fields': 'key'}
    headers={'Accept':'application/json'}
    try:
        # Use a GET with query params for a simple visibility check - avoids POST payload schema differences
        r = requests.get(SEARCH_URL, headers=headers, auth=auth, params=params, timeout=30)
        if r.status_code == 200:
            return True, r.status_code, 'ok'
        # Distinguish invalid vs permission vs other
        txt = (r.text or '')[:400]
        if r.status_code in (400,404):
            return False, r.status_code, f'Not visible or invalid for current credentials: {txt}'
        if r.status_code == 401:
            return False, r.status_code, 'Unauthorized (check username/token)'
        if r.status_code == 403:
            return False, r.status_code, 'Forbidden (token lacks browse permissions)'
        return False, r.status_code, txt
    except Exception as e:
        return False, -1, f'Exception during preflight: {e}'

def fetch_issue_detail(issue_key,auth):
    # No longer used: we fetch needed fields in the search call for speed.
    return None

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
            if sdt: elapsed=(datetime.now(timezone.utc)-sdt.replace(tzinfo=None)).total_seconds()/3600.0
    goal=goal_millis/3600000.0 if goal_millis else None
    breached=breach_time is not None
    return (elapsed,goal,breached,n)

def generate_ticket_rows(issues,ws,we):
    now_str=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    rows=[]
    for item in issues:
        k=item.get('key')
        fields=item.get('fields',{})
        issue_type = fields.get('issuetype',{}).get('name')
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
        # Remedy/Incident numbers: attempt via configured customfield, else parse from summary/description
        remedy_vals=[]
        remedy_cf=os.environ.get('REMEDY_TICKET_CUSTOMFIELD') or None
        if remedy_cf and fields.get(remedy_cf):
            remedy_vals.append(get_field_value(fields.get(remedy_cf)))
        # Fallbacks from common text sources
        remedy_vals.append(fields.get('summary'))
        remedy_vals.append(fields.get('description'))
        remedy_numbers=[]
        try:
            remedy_numbers=extract_incident_numbers([v for v in remedy_vals if v])
        except Exception:
            remedy_numbers=[]
        row={
            'T': issue_type,
            'Project': fields.get('project',{}).get('name'),
            'Key': k,
            'Summary': fields.get('summary'),
            'Status': fields.get('status',{}).get('name'),
            'Priority': get_field_value(fields.get('priority')),
            'Resolution': get_field_value(fields.get('resolution')),
            'Created': created,
            'Updated': updated,
            'Resolved': convert_ts(fields.get('resolutiondate')),
            'Reporter': get_field_value(fields.get('reporter')),
            'Assignee': get_field_value(fields.get('assignee')),
            'Component': [get_field_value(c) for c in fields.get('components',[])],
            'RemedyTicketNumber': remedy_numbers,
            'Links': extract_issue_links(fields.get('issuelinks')),
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
        ('T','STRING','NULLABLE'),
        ('Project','STRING','NULLABLE'),
        ('Key','STRING','REQUIRED'),
        ('Summary','STRING','NULLABLE'),
    ('Status','STRING','NULLABLE'),
    ('Priority','STRING','NULLABLE'),
    ('Resolution','STRING','NULLABLE'),
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
    # Ensure destination table exists and only perform schema ensure once per process
    table_key=f"{dataset}.{table}"
    if not table_exists(client,dataset,table):
        create_or_replace_table(client,dataset,table,schema)
        SCHEMA_ENSURED.add(table_key)
    elif table_key not in SCHEMA_ENSURED:
        # Ensure all columns exist with correct shapes; important for REPEATED fields
        ensure_table_columns(client,dataset,table,schema)
        SCHEMA_ENSURED.add(table_key)

    # Lazily create the temp table only when we actually have rows to insert
    temp_created=False
    max_results=100; start=0; total=float('inf'); batch=2000; buffer=[]; inserted=0
    while start<total:
        data=fetch_issues_page(auth,jql,start,max_results)
        if data is None:
            if temp_created:
                delete_table_quiet(client,dataset,temp)
            return False,inserted
        issues=data.get('issues',[]); total=data.get('total',0)
        if not issues:
            break
        rows=generate_ticket_rows(issues,ws,we)
        for r in rows:
            buffer.append(r)
            if len(buffer)>=batch:
                if not temp_created:
                    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp):
                        return False,inserted
                    temp_created=True
                if not insert_rows_with_retry(client,dataset,temp,buffer,schema):
                    if temp_created:
                        delete_table_quiet(client,dataset,temp)
                    return False,inserted
                inserted+=len(buffer); buffer=[]
        if buffer:
            if not temp_created and buffer:
                if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp):
                    return False,inserted
                temp_created=True
            if temp_created:
                if not insert_rows_with_retry(client,dataset,temp,buffer,schema):
                    delete_table_quiet(client,dataset,temp); return False,inserted
                inserted+=len(buffer)
            buffer=[]
        start+=len(issues); time.sleep(0.2)
    # If no rows were gathered for this window, skip MERGE to avoid unnecessary per-table quota usage
    if inserted==0:
        if temp_created:
            delete_table_quiet(client,dataset,temp)
        return True,0
    merge=f"""
    MERGE `{dataset}.{table}` T
    USING (
        SELECT * EXCEPT(rownum) FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) AS rownum FROM `{dataset}.{temp}`
        ) WHERE rownum = 1
    ) S
    ON T.Key = S.Key
    WHEN MATCHED THEN UPDATE SET
        T.T = S.T,
        Project = S.Project,
        Summary = S.Summary,
    Status = S.Status,
    Priority = S.Priority,
    Resolution = S.Resolution,
        Created = S.Created,
        Updated = S.Updated,
        Resolved = S.Resolved,
        Reporter = S.Reporter,
        Assignee = S.Assignee,
        Component = S.Component,
        RemedyTicketNumber = S.RemedyTicketNumber,
        Links = S.Links,
        {SR_REF_BQ_NAME} = S.{SR_REF_BQ_NAME},
        SyncTime = S.SyncTime,
        TimeToFirstResponse_Elapsed = S.TimeToFirstResponse_Elapsed,
        TimeToFirstResponse_Goal = S.TimeToFirstResponse_Goal,
        TimeToFirstResponse_Breached = S.TimeToFirstResponse_Breached,
        TimeToFirstResponse_Cycles = S.TimeToFirstResponse_Cycles,
        TimeToResolve_Elapsed = S.TimeToResolve_Elapsed,
        TimeToResolve_Goal = S.TimeToResolve_Goal,
        TimeToResolve_Breached = S.TimeToResolve_Breached,
        TimeToResolve_Cycles = S.TimeToResolve_Cycles,
        TimeToResolution_Elapsed = S.TimeToResolution_Elapsed,
        TimeToResolution_Goal = S.TimeToResolution_Goal,
        TimeToResolution_Breached = S.TimeToResolution_Breached,
        TimeToResolution_Cycles = S.TimeToResolution_Cycles,
        TimeToApproveNormalChange_Elapsed = S.TimeToApproveNormalChange_Elapsed,
        TimeToApproveNormalChange_Goal = S.TimeToApproveNormalChange_Goal,
        TimeToApproveNormalChange_Breached = S.TimeToApproveNormalChange_Breached,
        TimeToApproveNormalChange_Cycles = S.TimeToApproveNormalChange_Cycles,
        ProlongCase_Elapsed = S.ProlongCase_Elapsed,
        ProlongCase_Goal = S.ProlongCase_Goal,
        ProlongCase_Breached = S.ProlongCase_Breached,
        ProlongCase_Cycles = S.ProlongCase_Cycles,
        TimeToCloseAfterResolution_Elapsed = S.TimeToCloseAfterResolution_Elapsed,
        TimeToCloseAfterResolution_Goal = S.TimeToCloseAfterResolution_Goal,
        TimeToCloseAfterResolution_Breached = S.TimeToCloseAfterResolution_Breached,
        TimeToCloseAfterResolution_Cycles = S.TimeToCloseAfterResolution_Cycles,
        AppSupEscalation = S.AppSupEscalation
    WHEN NOT MATCHED THEN INSERT (
    T, Project, Key, Summary, Status, Priority, Resolution, Created, Updated, Resolved, Reporter, Assignee, Component, RemedyTicketNumber, Links, {SR_REF_BQ_NAME}, SyncTime,
        TimeToFirstResponse_Elapsed, TimeToFirstResponse_Goal, TimeToFirstResponse_Breached, TimeToFirstResponse_Cycles,
        TimeToResolve_Elapsed, TimeToResolve_Goal, TimeToResolve_Breached, TimeToResolve_Cycles,
        TimeToResolution_Elapsed, TimeToResolution_Goal, TimeToResolution_Breached, TimeToResolution_Cycles,
        TimeToApproveNormalChange_Elapsed, TimeToApproveNormalChange_Goal, TimeToApproveNormalChange_Breached, TimeToApproveNormalChange_Cycles,
        ProlongCase_Elapsed, ProlongCase_Goal, ProlongCase_Breached, ProlongCase_Cycles,
        TimeToCloseAfterResolution_Elapsed, TimeToCloseAfterResolution_Goal, TimeToCloseAfterResolution_Breached, TimeToCloseAfterResolution_Cycles,
        AppSupEscalation
    ) VALUES (
    S.T, S.Project, S.Key, S.Summary, S.Status, S.Priority, S.Resolution, S.Created, S.Updated, S.Resolved, S.Reporter, S.Assignee, S.Component, S.RemedyTicketNumber, S.Links, S.{SR_REF_BQ_NAME}, S.SyncTime,
        S.TimeToFirstResponse_Elapsed, S.TimeToFirstResponse_Goal, S.TimeToFirstResponse_Breached, S.TimeToFirstResponse_Cycles,
        S.TimeToResolve_Elapsed, S.TimeToResolve_Goal, S.TimeToResolve_Breached, S.TimeToResolve_Cycles,
        S.TimeToResolution_Elapsed, S.TimeToResolution_Goal, S.TimeToResolution_Breached, S.TimeToResolution_Cycles,
        S.TimeToApproveNormalChange_Elapsed, S.TimeToApproveNormalChange_Goal, S.TimeToApproveNormalChange_Breached, S.TimeToApproveNormalChange_Cycles,
        S.ProlongCase_Elapsed, S.ProlongCase_Goal, S.ProlongCase_Breached, S.ProlongCase_Cycles,
        S.TimeToCloseAfterResolution_Elapsed, S.TimeToCloseAfterResolution_Goal, S.TimeToCloseAfterResolution_Breached, S.TimeToCloseAfterResolution_Cycles,
        S.AppSupEscalation
    )
    """
    try:
        client.query(merge).result()
    except Exception as e:
        delete_table_quiet(client,dataset,temp); logging.exception(f'Merge failed: {e}'); return False,inserted
    delete_table_quiet(client,dataset,temp); return True,inserted

# ---------------- Logging buffer ----------------
def log_buf(pipeline,run_id,level,msg,fn=None,details=None):
    LOG_BUFFER.append({'Timestamp':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),'PipelineName':pipeline,'RunID':run_id,'LogLevel':level,'Message':msg,'FunctionName':fn,'Details':details})

def flush_logs(client,dataset,table):
    if not LOG_BUFFER: return
    # Legacy PipelineLogs removed; keep function as no-op to avoid noisy temp table errors
    return
    schema=[bigquery.SchemaField(n,t) for n,t in [
        ('Timestamp','TIMESTAMP'),('PipelineName','STRING'),('RunID','STRING'),('LogLevel','STRING'),('Message','STRING'),('FunctionName','STRING'),('Details','STRING')]]
    if not create_or_replace_table(client,dataset,temp,schema) or not wait_for_table(client,dataset,temp): return
    if not insert_rows_with_retry(client,dataset,temp,LOG_BUFFER,schema): return
    merge=f"MERGE `{dataset}.{table}` T USING (SELECT * FROM `{dataset}.{temp}`) S ON T.Timestamp=S.Timestamp AND T.RunID=S.RunID AND T.Message=S.Message WHEN MATCHED THEN UPDATE SET T.PipelineName=S.PipelineName,T.LogLevel=S.LogLevel,T.FunctionName=S.FunctionName,T.Details=S.Details WHEN NOT MATCHED THEN INSERT (Timestamp,PipelineName,RunID,LogLevel,Message,FunctionName,Details) VALUES (S.Timestamp,S.PipelineName,S.RunID,S.LogLevel,S.Message,S.FunctionName,S.Details)"
    client.query(merge).result(); delete_table_quiet(client,dataset,temp)
    # Clear buffer after successful flush
    try:
        LOG_BUFFER.clear()
    except Exception:
        # Fallback reassign if clear not available
        globals()['LOG_BUFFER'] = []

# ---------------- Main ----------------
def main():
    cfg=load_config();
    if not cfg: return
    dataset='GSO'; table='JiraTickets'; progress=f'{table}_progress'; pipeline='jira_tickets'; run_id=str(uuid.uuid4())
    base_days=7; min_start=datetime(2024,7,1,tzinfo=timezone.utc); client=bigquery.Client()
    run_started = datetime.now(timezone.utc)  # Track overall pipeline start time
    logging.info('Starting tickets pipeline')
    prog_schema=[bigquery.SchemaField(n,t) for n,t in [
        ('WindowStart','TIMESTAMP'),('WindowEnd','TIMESTAMP'),('Status','STRING'),('LastRun','TIMESTAMP'),('Projects','STRING'),('Project','STRING'),('RowCount','INT64')]]
    if not table_exists(client,dataset,progress): create_or_replace_table(client,dataset,progress,prog_schema)
    else:
        for col,ctype in [('Project','STRING'),('RowCount','INT64')]:
            try: client.query(f"ALTER TABLE `{dataset}.{progress}` ADD COLUMN IF NOT EXISTS {col} {ctype}").result()
            except Exception: pass
        # Ensure 429 metrics columns exist for alignment
        for col,ctype in [('Search429','INT64'),('Detail429','INT64')]:
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
        'Sherbet'
    ]
    # External file override (InitialSync/JQL.txt)
    default_projects = load_projects_from_file(default_projects)
    
    parser=argparse.ArgumentParser(); parser.add_argument('--project'); parser.add_argument('--projects'); args,_=parser.parse_known_args()
    # CLI precedence
    if args.projects:
        req=[p.strip() for p in args.projects.split(',') if p.strip()]
        lc_map={p.casefold():p for p in default_projects}
        projects=[lc_map[r.casefold()] for r in req if r.casefold() in lc_map]
    elif args.project:
        target=args.project.strip(); lc_map={p.casefold():p for p in default_projects}
        projects=[lc_map[target.casefold()]] if target.casefold() in lc_map else []
    else:
        projects=default_projects
    # Env overrides (SINGLE_PROJECT or PROJECTS) apply after CLI only if CLI not used
    if (not args.project and not args.projects):
        env_single=os.environ.get('SINGLE_PROJECT')
        env_projects=os.environ.get('PROJECTS') or os.environ.get('JIRA_PROJECTS')
    if env_single:
            target=env_single.strip()
            lc_map={p.casefold():p for p in default_projects}
            projects=[lc_map[target.casefold()]] if target.casefold() in lc_map else []
            logging.info(f'Using SINGLE_PROJECT env override -> {projects}')
    elif env_projects:
            req=[p.strip() for p in env_projects.split(',') if p.strip()]
            lc_map={p.casefold():p for p in default_projects}
            projects=[lc_map[r.casefold()] for r in req if r.casefold() in lc_map]
            logging.info(f'Using PROJECTS env override -> {projects}')
    # NOTE: TEST_PROJECTS override removed — use the full project list unless
    # overridden by CLI (--project / --projects) or env SINGLE_PROJECT / PROJECTS.
    if not projects: return
    logging.info(f'Final project list: {projects}')
    # Allow environment variable overrides for credentials
    user=os.environ.get('JIRA_USERNAME') or cfg.get('jira_username') or 'jjkli@consoleconnect.com'
    token=os.environ.get('JIRA_API_TOKEN') or cfg.get('jira_api_token')
    if not token: logging.error('jira_api_token missing'); return
    auth=(user,token)
    # Shared-filter logic removed per operator request — always use per-project JQL
    filter_jql = None
    use_filter = False
    for proj in projects:
        logging.info(f'Starting backfill for project {proj}')
        ok, sc, msg = preflight_validate_project(auth, proj)
        if not ok:
            logging.error(f'Preflight failed for project "{proj}" status={sc} detail={msg}. Skipping this project.')
            log_pipeline_run(None, pipeline_name=PIPELINE_NAME, run_id=run_id, level="ERROR", message=f'Preflight failed {proj}: {msg}', status="ERROR")
            continue
        log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message=f"Starting backfill for project {proj}", status="RUNNING")
        # Cleanup: mark tiny leftover progress windows as degraded so we don't churn on 10-30s windows
        try:
            cleanup_cfg=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter('p','STRING',proj),
                bigquery.ScalarQueryParameter('minsec','INT64',MIN_PROGRESS_WINDOW_SEC)
            ])
            cleanup_sql=(
                f"UPDATE `{dataset}.{progress}` "
                "SET Status='degraded', LastRun=CURRENT_TIMESTAMP() "
                "WHERE Project=@p AND Status NOT IN ('complete','degraded') "
                "AND TIMESTAMP_DIFF(WindowEnd, WindowStart, SECOND) < @minsec"
            )
            job=client.query(cleanup_sql,job_config=cleanup_cfg); job.result()
            affected=getattr(job,'num_dml_affected_rows',None)
            if affected:
                logging.info(f'Project {proj}: cleaned up {affected} tiny progress windows (<{MIN_PROGRESS_WINDOW_SEC}s)')
        except Exception:
            pass
        last_completed_start=None
        while True:
            cfgq=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter('p','STRING',proj),
            ])
            cfgq_with_min=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter('p','STRING',proj),
                bigquery.ScalarQueryParameter('minsec','INT64',MIN_PROGRESS_WINDOW_SEC)
            ])
            ws=None; we=None
            # Allow a test override for a single forced historic window via env vars
            test_ws, test_we = parse_test_window_env()
            if test_ws and test_we:
                ws = test_ws
                we = test_we
            else:
                try:
                    # Only pick outstanding windows that are not tiny; tiny ones are ignored (or cleaned up above)
                    res=client.query(
                        f"SELECT WindowStart,WindowEnd FROM `{dataset}.{progress}` WHERE Project=@p AND Status NOT IN ('complete','degraded') AND TIMESTAMP_DIFF(WindowEnd, WindowStart, SECOND) >= @minsec ORDER BY WindowStart ASC LIMIT 1",
                        job_config=cfgq_with_min
                    ).result()
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
                    latest_aware = to_utc_aware(latest)
                    last_completed_aware = to_utc_aware(last_completed_start) if last_completed_start else None
                    # If we're too close to now, skip making a tiny window and move to next project
                    try:
                        now_tmp = datetime.now(timezone.utc)
                        if (now_tmp - latest_aware).total_seconds() < MIN_PROGRESS_WINDOW_SEC:
                            logging.info(f'Project {proj}: latest completed window end is too recent; skipping tiny near-now window and moving on')
                            # Exit project loop to move on to next project
                            break
                    except Exception:
                        pass
                    cand_start=latest_aware - overlap
                    if last_completed_aware and cand_start<=last_completed_aware: cand_start=latest_aware
                    if last_completed_aware and (latest_aware-last_completed_aware)<=overlap*2: cand_start=latest_aware
                    if cand_start<min_start: cand_start=min_start
                    ws=cand_start
                else:
                    ws=min_start
                cand_end=ws+timedelta(days=adaptive)
            ws = to_utc_aware(ws) if ws else ws
            now = datetime.now(timezone.utc)
            cand_end = to_utc_aware(cand_end) if cand_end else cand_end
            we = min(cand_end, now)
            # Enforce a minimum window length to avoid thrashing on tiny windows
            try:
                if (we - ws).total_seconds() < MIN_PROGRESS_WINDOW_SEC:
                    min_ws = we - timedelta(seconds=MIN_PROGRESS_WINDOW_SEC)
                    # Respect min_start and last_completed_start
                    if min_ws < min_start:
                        min_ws = min_start
                    if last_completed_start and min_ws < last_completed_start:
                        min_ws = last_completed_start
                    # Ensure ws < we after adjustments
                    if min_ws >= we:
                        min_ws = we - timedelta(seconds=MIN_PROGRESS_WINDOW_SEC)
                    ws = min_ws
            except Exception:
                pass
            if ws>=now: break
            proj_clause=f'project = "{proj}"' if any(ch in proj for ch in [' ','&']) else f'project = {proj}'
            if use_filter:
                jql=f"({filter_jql}) AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
            else:
                jql=f"({proj_clause}) AND updated >= \"{ws.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{we.strftime('%Y/%m/%d %H:%M')}\""
            try:
                merge=(
                    f"MERGE `{dataset}.{progress}` T USING (SELECT TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS WindowStart, TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS WindowEnd, '{proj}' AS Project) S "
                    "ON T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd AND T.Project=S.Project "
                    "WHEN MATCHED THEN UPDATE SET Status='in_progress', LastRun=CURRENT_TIMESTAMP(), Project=S.Project "
                    "WHEN NOT MATCHED THEN INSERT (WindowStart,WindowEnd,Status,LastRun,Project) VALUES (S.WindowStart,S.WindowEnd,'in_progress',CURRENT_TIMESTAMP(),S.Project)"
                ); client.query(merge).result()
                logging.info(f'Project {proj} window {ws} -> {we} marked in_progress')
                # window marked in progress; log RUNNING for this slice
                log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message="Window in_progress", status="RUNNING", window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'))
            except Exception:
                break
            success=False; rc=0
            window_start_time = datetime.now(timezone.utc)  # Track window processing start time
            global SEARCH_429_COUNT, DETAIL_429_COUNT, CURRENT_TICKET_WORKERS, _NO429_STREAK
            SEARCH_429_COUNT=0; DETAIL_429_COUNT=0
            logging.info(f'Executing JQL: {jql}')
            try: success,rc=sync_tickets_window(jql,auth,client,dataset,table,ws,we)
            except Exception as e:
                log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="ERROR", message=f"Fatal {proj} {ws}->{we} {e}", status="ERROR")
            degraded=False
            if success:
                ratio=DETAIL_429_COUNT/max(1,rc)
                if ratio>FAILURE_RATIO_DEGRADED: degraded=True
            status='degraded' if degraded else ('complete' if success else 'failed')
            window_end_time = datetime.now(timezone.utc)
            window_duration_seconds = (window_end_time - window_start_time).total_seconds()
            upd=(
                f"UPDATE `{dataset}.{progress}` SET Status='{status}', LastRun=CURRENT_TIMESTAMP(), RowCount={rc}, Search429={SEARCH_429_COUNT}, Detail429={DETAIL_429_COUNT} "
                f"WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND Status!='complete'"
            ); client.query(upd).result()
            logging.info(f'Project {proj} window {ws}->{we} {status} rows={rc} 429_search={SEARCH_429_COUNT} 429_detail={DETAIL_429_COUNT}')
            log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level=("INFO" if success else "ERROR"), message=f'Window {status} {proj}', status=("SUCCESS" if success else "ERROR"), window_start=ws.strftime('%Y-%m-%d %H:%M:%S'), window_end=we.strftime('%Y-%m-%d %H:%M:%S'), rows_merged=int(rc), duration_seconds=window_duration_seconds)
            # If we used a TEST_WINDOW_START/END override, only run that single forced window then exit the project loop
            try:
                if 'TEST_WINDOW_START' in os.environ and 'TEST_WINDOW_END' in os.environ:
                    logging.info('TEST_WINDOW override processed; exiting project loop after one forced window')
                    break
            except Exception:
                pass
            if status in ('complete','degraded'):
                last_completed_start=ws
                if (SEARCH_429_COUNT>0 or DETAIL_429_COUNT>0):
                    CURRENT_TICKET_WORKERS=max(TICKET_MIN_WORKERS,int(CURRENT_TICKET_WORKERS*TICKET_SCALE_DOWN_FACTOR)); _NO429_STREAK=0
                    logging.info(f'Scaling down detail workers to {CURRENT_TICKET_WORKERS}')
                else:
                    _NO429_STREAK+=1
                    if _NO429_STREAK>=TICKET_SCALE_UP_NO429_WINDOWS and CURRENT_TICKET_WORKERS<TICKET_MAX_WORKERS:
                        CURRENT_TICKET_WORKERS=min(TICKET_MAX_WORKERS,max(CURRENT_TICKET_WORKERS+1,int(CURRENT_TICKET_WORKERS*TICKET_SCALE_UP_FACTOR))); _NO429_STREAK=0
                        logging.info(f'Scaling up detail workers to {CURRENT_TICKET_WORKERS}')
            if not success:
                try: span_hours=(we-ws).total_seconds()/3600.0
                except Exception: span_hours=0
                if span_hours>(MIN_SHRINK_HOURS+0.05):
                    new_span=max(MIN_SHRINK_HOURS,span_hours*RATE_SHRINK_FACTOR); new_end=ws+timedelta(hours=new_span)
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET WindowEnd=TIMESTAMP('{new_end.strftime('%Y-%m-%d %H:%M:%S.%f')}'), Status='failed' "
                            f"WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING)"
                        ).result();
                        continue
                    except Exception: break
                else:
                    try:
                        client.query(
                            f"UPDATE `{dataset}.{progress}` SET Status='degraded' WHERE Project='{proj}' AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{we.strftime('%Y-%m-%d %H:%M:%S.%f')}') AS STRING) AND Status='failed'"
                        ).result()
                    except Exception: pass
                    break
            # Legacy flush disabled (no-op)
        log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message=f"Project {proj} finished", status="SUCCESS")
    run_ended = datetime.now(timezone.utc)
    duration_seconds = (run_ended - run_started).total_seconds()
    log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level="INFO", message="Tickets pipeline finished", status="SUCCESS", duration_seconds=duration_seconds)

if __name__=='__main__':
    main()
