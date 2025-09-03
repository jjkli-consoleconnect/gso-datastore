import requests
import sys, pathlib
_script_dir = pathlib.Path(__file__).resolve().parent
_repo_root = str(_script_dir.parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
import json
import os, sys, pathlib
from google.cloud import bigquery
import logging
from datetime import datetime, timedelta
import time
import uuid
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure repository root (parent of InitialSync/) in sys.path for shared imports
_script_dir = pathlib.Path(__file__).resolve().parent
_root_dir = _script_dir.parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

# Auto GOOGLE_APPLICATION_CREDENTIALS if not set
if 'GOOGLE_APPLICATION_CREDENTIALS' not in os.environ:
    for cand in ('service-account.json','jira-bigquery-key.json'):
        p=_root_dir / cand
        if p.exists():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS']=str(p)
            break

from shared.pipeline_runs_logger import log_pipeline_run

# ----------------- CONFIG -----------------
DEBUG = False
logging.basicConfig(level=logging.INFO if not DEBUG else logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Changelog initial sync starting up")

LOG_BUFFER = []  # buffered logs for batch write (legacy; PipelineRuns used instead)
PIPELINE_NAME = 'jira_changelog_initialsync'

# -------- Data completeness / rate-limit resiliency settings --------
MAX_HISTORY_ATTEMPTS = 5              # per-issue history retries
HISTORY_RETRY_BASE_SLEEP = 2          # base sleep for non-429 retries (exponential backoff)
HISTORY_REQUEUE_COOLDOWN = 10         # seconds before requeue second pass
FAILURE_RATIO_DEGRADED = 0.02         # >2% remaining failed issue histories => degraded
OVERLAP_MINUTES = 10                  # small overlap between windows to catch late or missed events
JITTER_MAX_SECONDS = 0.3              # jitter for smoothing parallel request bursts
SECOND_PASS_MAX_WORKERS = 4           # reduced concurrency during requeue

# Rate limiting / dynamic concurrency
RATE_BUCKET_CAPACITY = 120            # max tokens in bucket (rough target: requests per minute)
RATE_BUCKET_REFILL_PER_SEC = 2        # tokens refilled each second (2 * 60 = 120/minute)
RATE_MIN_SLEEP = 0.05                 # minimum sleep while waiting for token
HISTORY_MAX_WORKERS_BASE = 16         # starting upper bound for history concurrency
HISTORY_MIN_WORKERS = 4               # floor
HISTORY_MAX_WORKERS = 24              # ceiling if conditions are good
HISTORY_SCALE_UP_NO429_WINDOWS = 2    # consecutive windows without 429 to scale up
HISTORY_SCALE_DOWN_FACTOR = 0.6       # multiply current workers on 429 burst
HISTORY_SCALE_UP_FACTOR = 1.2         # multiply current workers when scaling up

CURRENT_HISTORY_WORKERS = HISTORY_MAX_WORKERS_BASE
_NO429_STREAK = 0

# Global counters (reset each window) for metrics
SEARCH_429_COUNT = 0
HISTORY_429_COUNT = 0

import threading
class TokenBucket:
    def __init__(self, capacity, refill_per_sec):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_sec = refill_per_sec
        self.last = time.time()
        self.lock = threading.Lock()
    def take(self, amount=1):
        while True:
            with self.lock:
                now_t = time.time()
                elapsed = now_t - self.last
                if elapsed > 0:
                    refill = elapsed * self.refill_per_sec
                    if refill > 0:
                        self.tokens = min(self.capacity, self.tokens + refill)
                        self.last = now_t
                if self.tokens >= amount:
                    self.tokens -= amount
                    return True
            time.sleep(RATE_MIN_SLEEP)

RATE_LIMITER = TokenBucket(RATE_BUCKET_CAPACITY, RATE_BUCKET_REFILL_PER_SEC)


# -------- Adaptive window tuning thresholds --------
# These thresholds allow dynamic shrinking/expansion of window length to cope with spikes.
# Tunable constants (row counts per completed window):
ADAPT_HIGH_ROWS = 50000      # if last window > this, halve window length (down to min 6h)
ADAPT_MEDIUM_ROWS = 15000    # if last window > this (but <= high), shrink toward 12h+ as needed
ADAPT_LOW_ROWS = 2000        # if consistently below this we can regrow window length
ADAPT_GROW_CONSECUTIVE = 3   # consecutive low windows required before expansion
MAX_GROW_DAYS = 7            # never expand beyond base 7 days
MIN_SHRINK_HOURS = 6         # minimum window length when shrinking

# Rate-based adaptive shrink (respond to Jira throttling even if row counts moderate)
RATE_SHRINK_HISTORY_429 = 25   # if previous window had >= this many history 429s, shrink next window
RATE_SHRINK_SEARCH_429 = 8     # if previous window had >= this many search 429s, shrink next window
RATE_SHRINK_FACTOR = 0.5       # multiply previous window span by this when rate-shrink triggered

MIN_WINDOW_MINUTES = 30         # minimum window size in minutes to prevent tiny windows

# ----------------- UTIL -----------------
def load_config():
    """Layered Jira config load with fallbacks.
    1. Env JIRA_CONFIG_JSON (JSON)
    2. Local config.json (script dir)
    3. Repo root config.json
    4. Hourly/jira_tickets/config.json (reuse working long token)
    """
    env_cfg=os.environ.get('JIRA_CONFIG_JSON')
    if env_cfg:
        try:
            data=json.loads(env_cfg)
            logging.info('Loaded Jira config from env JIRA_CONFIG_JSON')
            return data
        except Exception:
            logging.warning('Failed to parse JIRA_CONFIG_JSON env var')
    candidates=[str(_script_dir/'config.json'), str(_root_dir/'config.json'), str(_root_dir/'Hourly'/'jira_tickets'/'config.json')]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path,'r',encoding='utf-8') as f:
                data=json.load(f)
            token=data.get('jira_api_token')
            if token and len(token)<40:
                logging.warning(f'Loaded very short jira_api_token (len={len(token)}) from {path}; may be invalid')
            else:
                logging.info(f'Loaded Jira config from {path} (token length {len(token) if token else 0})')
            return data
        except Exception as e:
            logging.debug(f'Config read fail {path}: {e}')
    logging.error('No Jira config found in expected locations')
    return None


def convert_timestamp(ts: str):
    if not ts:
        return None
    # Try multiple Jira timestamp formats
    fmts = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S'
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(ts, fmt)
            # Strip tzinfo for consistency
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
    logging.warning(f"Could not parse timestamp: {ts}")
    return None

def load_projects_from_file(defaults):
    """Load project names from external file for Docker/local usage with extended comment support.
    Supports:
      - Full-line comments starting with #, //, --
      - Inline comments after space + marker ( #, //, -- )
      - Blank line ignoring
    Resolution order unchanged.
    """
    candidates = []
    try:
        env_path = os.environ.get('JQL_FILE') or os.environ.get('PROJECTS_FILE')
        if env_path:
            candidates.append(env_path)
        script_dir = os.path.dirname(__file__)
        candidates.append(os.path.normpath(os.path.join(script_dir, '..', 'JQL.txt')))
        candidates.extend([
            '/app/InitialSync/JQL.txt',
            '/config/JQL.txt',
            '/data/JQL.txt',
        ])
        comment_starts = ('#','//','--')
        inline_markers = [' #',' //',' -- ']
        for p in candidates:
            try:
                if not p or not os.path.exists(p):
                    continue
                with open(p, 'r', encoding='utf-8') as f:
                    raw_lines = f.readlines()
                items = []
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
                    logging.info(f"Loaded project list from {p} ({len(items)} entries)")
                    return items
            except Exception as ie:
                logging.debug(f"Project list read failed for {p}: {ie}")
    except Exception as e:
        logging.debug(f"Could not resolve external project list: {e}")
    return defaults

def preflight_validate_project(auth, project_name, base_url='https://consoleconnect.atlassian.net'):
    """Lightweight visibility check before heavy backfill. Returns (ok, status_code, message)."""
    search_url=f'{base_url}/rest/api/2/search'
    test_jql=f'project = "{project_name}"'
    payload=json.dumps({'jql':test_jql,'startAt':0,'maxResults':0,'fields':['key']})
    headers={'Accept':'application/json','Content-Type':'application/json'}
    try:
        r=requests.post(search_url,headers=headers,auth=auth,data=payload,timeout=30)
        if r.status_code==200:
            return True, r.status_code, 'ok'
        snippet=(r.text or '')[:300].replace('\n',' ')
        if r.status_code in (400,404):
            return False, r.status_code, f'Not visible/invalid: {snippet}'
        if r.status_code==401:
            return False, r.status_code, 'Unauthorized'
        if r.status_code==403:
            return False, r.status_code, 'Forbidden'
        return False, r.status_code, snippet
    except Exception as e:
        return False, -1, f'Exception: {e}'

# -------------- BigQuery helpers --------------

def create_or_replace_table(client, dataset_id, table_id, schema):
    try:
        query = f"CREATE OR REPLACE TABLE `{dataset_id}.{table_id}` (" \
                + ', '.join(f'`{f.name}` {f.field_type}' for f in schema) + ")"
        client.query(query).result()
        logging.debug(f"(Re)created table {dataset_id}.{table_id}")
        return True
    except Exception as e:
        logging.exception(f"Error creating/replacing table {dataset_id}.{table_id}: {e}")
        return False

def table_exists(client, dataset_id, table_id):
    try:
        client.get_table(f"{dataset_id}.{table_id}")
        return True
    except Exception as e:
        if 'Not found' in str(e):
            return False
        logging.exception(f"Error checking table {dataset_id}.{table_id}: {e}")
        return False

def wait_for_table(client, dataset_id, table_id, retries=15, delay=4):
    for i in range(retries):
        if table_exists(client, dataset_id, table_id):
            return True
        time.sleep(delay)
    logging.error(f"Table {dataset_id}.{table_id} not available after waits")
    return False

def insert_rows_with_retry(client, dataset_id, table_id, rows, schema, retries=6, delay=6):
    if not rows:
        return True
    table_ref = client.dataset(dataset_id).table(table_id)
    for attempt in range(retries):
        try:
            errors = client.insert_rows_json(table_ref, rows)
            if not errors:
                logging.info(f"Inserted {len(rows)} rows -> {dataset_id}.{table_id}")
                return True
            logging.error(f"Insert errors (attempt {attempt+1}): {errors}")
        except Exception as e:
            if 'Not found' in str(e):
                logging.warning(f"Temp table missing {dataset_id}.{table_id}; recreating")
                if not create_or_replace_table(client, dataset_id, table_id, schema) or not wait_for_table(client, dataset_id, table_id):
                    return False
            else:
                logging.exception(f"Insert exception attempt {attempt+1}: {e}")
        if attempt < retries - 1:
            time.sleep(delay)
    return False

def delete_table_quiet(client, dataset_id, table_id):
    try:
        client.delete_table(f"{dataset_id}.{table_id}")
        logging.debug(f"Deleted temp table {dataset_id}.{table_id}")
    except Exception as e:
        if 'Not found' in str(e):
            return
        logging.warning(f"Could not delete temp table {dataset_id}.{table_id}: {e}")

# -------------- Jira fetch helpers --------------

def fetch_issues_page(search_url, auth, headers, jql, start_at, max_results):
    payload = json.dumps({
        'jql': jql,
        'startAt': start_at,
        'maxResults': max_results,
        'fields': ['key']
    })
    for attempt in range(5):
        try:
            RATE_LIMITER.take()
            resp = requests.post(search_url, headers=headers, auth=auth, data=payload, timeout=300)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logging.warning(f"Search timeout attempt {attempt+1}/5 startAt={start_at}")
            time.sleep(15)
        except requests.RequestException as e:
            status = e.response.status_code if e.response else 'NA'
            if status == 429:
                global SEARCH_429_COUNT
                SEARCH_429_COUNT += 1
                retry_after = int(e.response.headers.get('Retry-After', 30)) if e.response else 30
                sleep_for = retry_after + random.uniform(0, JITTER_MAX_SECONDS)
                logging.warning(f"Rate limited 429 search attempt {attempt+1}/5; sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue
            logging.error(f"Search error attempt {attempt+1}/5: {e} status={status}")
            if attempt < 4:
                time.sleep(10)
            else:
                return None
    return None

def fetch_histories_for_issue(base_url, issue_key, auth):
    """Fetch single issue with changelog, retrying on 429 & transient errors.
    Returns (data, attempts, last_error_str, had_429)"""
    global HISTORY_429_COUNT
    url = f"{base_url}/rest/api/2/issue/{issue_key}?expand=changelog"
    last_err = None
    had_429 = False
    for attempt in range(1, MAX_HISTORY_ATTEMPTS + 1):
        try:
            RATE_LIMITER.take()
            resp = requests.get(url, auth=auth, timeout=180)
            if resp.status_code == 429:
                HISTORY_429_COUNT += 1
                had_429 = True
                retry_after = int(resp.headers.get('Retry-After', 10))
                sleep_for = retry_after + random.uniform(0, JITTER_MAX_SECONDS)
                logging.warning(f"429 history {issue_key} attempt {attempt}/{MAX_HISTORY_ATTEMPTS} retry_after={retry_after}s")
                time.sleep(sleep_for)
                continue
            if resp.status_code >= 500:
                last_err = f"{resp.status_code} server error"
                back = min(60, HISTORY_RETRY_BASE_SLEEP * (2 ** (attempt - 1))) + random.uniform(0, JITTER_MAX_SECONDS)
                logging.warning(f"Server error {resp.status_code} history {issue_key} attempt {attempt} sleeping {back:.1f}s")
                time.sleep(back)
                continue
            resp.raise_for_status()
            return resp.json(), attempt, None, had_429
        except requests.RequestException as e:
            last_err = str(e)
            back = min(60, HISTORY_RETRY_BASE_SLEEP * (2 ** (attempt - 1))) + random.uniform(0, JITTER_MAX_SECONDS)
            if attempt < MAX_HISTORY_ATTEMPTS:
                logging.warning(f"History fetch failed {issue_key} attempt {attempt}/{MAX_HISTORY_ATTEMPTS}: {e}; retrying in {back:.1f}s")
                time.sleep(back)
            else:
                logging.warning(f"History fetch failed permanently {issue_key}: {e}")
    return None, MAX_HISTORY_ATTEMPTS, last_err, had_429

def fetch_histories_batch(base_url, issue_keys, auth, max_workers=None):
    """Parallel fetch with retries per issue and second-pass requeue for misses."""
    results = {}
    meta = {}  # issue_key -> (attempts, error, had_429)
    def worker(k):
        data, attempts, err, had_429 = fetch_histories_for_issue(base_url, k, auth)
        return k, data, attempts, err, had_429
    if max_workers is None:
        max_workers = CURRENT_HISTORY_WORKERS
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {ex.submit(worker, k): k for k in issue_keys}
        for fut in as_completed(future_map):
            k = future_map[fut]
            try:
                issue_key, data, attempts, err, had_429 = fut.result()
                results[issue_key] = data
                meta[issue_key] = (attempts, err, had_429)
            except Exception as e:
                logging.warning(f"Worker exception {k}: {e}")
                results[k] = None
                meta[k] = (1, str(e), False)
            time.sleep(0.02 + random.uniform(0, 0.05))  # micro pacing
    # Requeue failures (None) once after cooldown
    failed = [k for k, v in results.items() if v is None]
    if failed:
        logging.info(f"Requeue pass for {len(failed)} failed issues after cooldown {HISTORY_REQUEUE_COOLDOWN}s")
        time.sleep(HISTORY_REQUEUE_COOLDOWN)
        with ThreadPoolExecutor(max_workers=min(SECOND_PASS_MAX_WORKERS, max(1, len(failed)))) as ex:
            future_map = {ex.submit(worker, k): k for k in failed}
            for fut in as_completed(future_map):
                k = future_map[fut]
                try:
                    issue_key, data, attempts, err, had_429 = fut.result()
                    results[issue_key] = data
                    meta[issue_key] = (meta.get(issue_key, (0, None, False))[0] + attempts, err, had_429 or meta.get(issue_key,(0,None,False))[2])
                except Exception as e:
                    logging.warning(f"Second pass worker exception {k}: {e}")
                    results[k] = None
                    base_attempts = meta.get(k, (0, None, False))[0]
                    meta[k] = (base_attempts + 1, str(e), meta.get(k,(0,None,False))[2])
                time.sleep(0.05 + random.uniform(0, 0.1))
    return results, meta

# -------------- Changelog row generation --------------

def generate_changelog_rows(issues, histories_map, window_start, window_end):
    utc_now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    ws = window_start.replace(tzinfo=None) if getattr(window_start, 'tzinfo', None) else window_start
    we = window_end.replace(tzinfo=None) if getattr(window_end, 'tzinfo', None) else window_end
    for issue in issues:
        key = issue.get('key') if issue else None
        if not key:
            continue
        issue_data = histories_map.get(key)
        if not issue_data:
            continue
        histories = issue_data.get('changelog', {}).get('histories', [])
        for h in histories:
            hist_id = h.get('id')
            created_raw = h.get('created')
            created_conv = convert_timestamp(created_raw)
            if not created_conv:
                continue
            try:
                created_dt = datetime.strptime(created_conv, '%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
            if not (ws <= created_dt < we):
                continue
            author = h.get('author', {})
            for item in h.get('items', []):
                if (item.get('fieldId') == 'status') or (item.get('field') == 'status'):
                    yield {
                        'Issue_Key': key,
                        'History_ID': hist_id,
                        'Transition_Timestamp': created_conv,
                        'Transitioned_From': item.get('fromString'),
                        'Transitioned_To': item.get('toString'),
                        'Transitioned_By_Account_ID': author.get('accountId'),
                        'Transitioned_By_Display_Name': author.get('displayName'),
                        'SyncTime': utc_now,
                        # InsertedAt removed (use SyncTime only)
                    }

# -------------- Sync core --------------

def sync_changelog_window(base_url, jql, auth, client, dataset_id, table_id, window_start, window_end):
    run_id = str(uuid.uuid4())
    temp_table = f'JiraChangelog_temp_{run_id}'
    schema = [
        bigquery.SchemaField('Issue_Key', 'STRING'),
        bigquery.SchemaField('History_ID', 'STRING'),
        bigquery.SchemaField('Transition_Timestamp', 'TIMESTAMP'),
        bigquery.SchemaField('Transitioned_From', 'STRING'),
        bigquery.SchemaField('Transitioned_To', 'STRING'),
        bigquery.SchemaField('Transitioned_By_Account_ID', 'STRING'),
        bigquery.SchemaField('Transitioned_By_Display_Name', 'STRING'),
        bigquery.SchemaField('SyncTime', 'TIMESTAMP'),
    ]
    # Ensure destination table exists with required columns; add missing columns if legacy schema
    try:
        if not table_exists(client, dataset_id, table_id):
            create_or_replace_table(client, dataset_id, table_id, schema)
        else:
            # Add new column if it doesn't exist (SyncTime)
            client.query(f"ALTER TABLE `{dataset_id}.{table_id}` ADD COLUMN IF NOT EXISTS SyncTime TIMESTAMP").result()
    except Exception as e:
        logging.warning(f"Could not ensure target table schema: {e}")

    if not create_or_replace_table(client, dataset_id, temp_table, schema) or not wait_for_table(client, dataset_id, temp_table):
        return False, 0

    search_url = f"{base_url}/rest/api/2/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    max_results = 100
    start_at = 0
    total = float('inf')
    batch_size = 1000
    rows_buffer = []
    total_rows = 0

    while start_at < total:
        data = fetch_issues_page(search_url, auth, headers, jql, start_at, max_results)
        if data is None:
            logging.error("Issue search failed permanently; aborting window.")
            delete_table_quiet(client, dataset_id, temp_table)
            return False, 0
        issues = data.get('issues', [])
        total = data.get('total', 0)
        if not issues:
            break
        issue_keys = [i.get('key') for i in issues if i.get('key')]
        histories_map, histories_meta = fetch_histories_batch(base_url, issue_keys, auth)
        for row in generate_changelog_rows(issues, histories_map, window_start, window_end):
            rows_buffer.append(row)
            if len(rows_buffer) >= batch_size:
                if not insert_rows_with_retry(client, dataset_id, temp_table, rows_buffer, schema):
                    delete_table_quiet(client, dataset_id, temp_table)
                    return False, total_rows
                total_rows += len(rows_buffer)
                rows_buffer = []
        if rows_buffer:
            if not insert_rows_with_retry(client, dataset_id, temp_table, rows_buffer, schema):
                delete_table_quiet(client, dataset_id, temp_table)
                return False, total_rows
            total_rows += len(rows_buffer)
            rows_buffer = []
        start_at += len(issues)
        logging.info(f"Processed issues {start_at}/{total}")
        time.sleep(1)

    logging.info(f"Inserted total {total_rows} changelog rows into temp table {temp_table}")
    # Merge
    merge_query = f"""
        MERGE `{dataset_id}.{table_id}` T
        USING (
            SELECT DISTINCT Issue_Key, History_ID, Transition_Timestamp, Transitioned_From, Transitioned_To,
                            Transitioned_By_Account_ID, Transitioned_By_Display_Name, SyncTime
            FROM `{dataset_id}.{temp_table}`
        ) S
        ON T.History_ID = S.History_ID AND T.Transition_Timestamp = S.Transition_Timestamp
        WHEN MATCHED THEN UPDATE SET
            T.Issue_Key = S.Issue_Key,
            T.Transitioned_From = S.Transitioned_From,
            T.Transitioned_To = S.Transitioned_To,
            T.Transitioned_By_Account_ID = S.Transitioned_By_Account_ID,
            T.Transitioned_By_Display_Name = S.Transitioned_By_Display_Name,
            T.SyncTime = S.SyncTime
    WHEN NOT MATCHED THEN INSERT (Issue_Key, History_ID, Transition_Timestamp, Transitioned_From, Transitioned_To,
                      Transitioned_By_Account_ID, Transitioned_By_Display_Name, SyncTime)
    VALUES (S.Issue_Key, S.History_ID, S.Transition_Timestamp, S.Transitioned_From, S.Transitioned_To,
        S.Transitioned_By_Account_ID, S.Transitioned_By_Display_Name, S.SyncTime)
    """
    try:
        client.query(merge_query).result()
        logging.info("Merge completed into final changelog table")
    except Exception as e:
        logging.exception(f"Merge failed: {e}")
        delete_table_quiet(client, dataset_id, temp_table)
        return False, total_rows

    delete_table_quiet(client, dataset_id, temp_table)
    return True, total_rows

# -------------- Logging buffer -> BigQuery --------------

def log_to_bigquery_buffer(pipeline_name, run_id, level, message, function_name=None, details=None):
    LOG_BUFFER.append({
        'Timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'PipelineName': pipeline_name,
        'RunID': run_id,
        'LogLevel': level,
        'Message': message,
        'FunctionName': function_name,
        'Details': details
    })

def flush_logs(client, dataset_id, log_table):
    # Legacy PipelineLogs flush disabled (no-op). Use PipelineRuns table instead.
    return

# -------------- Main orchestration --------------

def main():
    config = load_config()
    if not config:
        return

    dataset_id = 'GSO'
    table_id = 'JiraChangelog'
    # Legacy PipelineLogs table unused after migration
    pipeline_name = 'jira_changelog'
    run_id = str(uuid.uuid4())
    jira_url = 'https://consoleconnect.atlassian.net'

    window_days = 7
    min_ts = datetime(2024, 7, 1)
    now = datetime.utcnow()

    progress_table = f"{table_id}_progress"
    # Extended schema to support per-project tracking (Project column). Keep legacy 'Projects' if present.
    progress_schema = [
        bigquery.SchemaField('WindowStart', 'TIMESTAMP'),
        bigquery.SchemaField('WindowEnd', 'TIMESTAMP'),
        bigquery.SchemaField('Status', 'STRING'),
        bigquery.SchemaField('LastRun', 'TIMESTAMP'),
        bigquery.SchemaField('Projects', 'STRING'),  # legacy aggregate list
        bigquery.SchemaField('Project', 'STRING'),   # new per-project field
        bigquery.SchemaField('RowCount', 'INT64'),   # rows processed in window
        bigquery.SchemaField('Search429', 'INT64'),  # number of search endpoint 429s in window
        bigquery.SchemaField('History429', 'INT64'), # number of history endpoint 429s in window
    ]

    try:
        client = bigquery.Client()
    except Exception as e:
        logging.exception(f"BigQuery client init failed: {e}")
        return

    if not table_exists(client, dataset_id, progress_table):
        create_or_replace_table(client, dataset_id, progress_table, progress_schema)
    else:
        # Attempt to add Project column if legacy table exists
        try:
            client.query(f"ALTER TABLE `{dataset_id}.{progress_table}` ADD COLUMN IF NOT EXISTS Project STRING").result()
            client.query(f"ALTER TABLE `{dataset_id}.{progress_table}` ADD COLUMN IF NOT EXISTS RowCount INT64").result()
            client.query(f"ALTER TABLE `{dataset_id}.{progress_table}` ADD COLUMN IF NOT EXISTS Search429 INT64").result()
            client.query(f"ALTER TABLE `{dataset_id}.{progress_table}` ADD COLUMN IF NOT EXISTS History429 INT64").result()
        except Exception:
            pass

    # User-specified project list (order determines processing sequence); can be filtered by CLI args
    project_list_default = [
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
        'Customer Success Management'
    ]
    # Try external file override (InitialSync/JQL.txt)
    project_list_default = load_projects_from_file(project_list_default)
    # Parse CLI args early to filter project list
    import argparse, sys
    parser = argparse.ArgumentParser(description='Jira changelog initial sync')
    parser.add_argument('--project', help='Single project to process')
    parser.add_argument('--projects', help='Comma separated list of projects to process (overrides --project)')
    args, unknown = parser.parse_known_args()
    if args.projects:
        requested = [p.strip() for p in args.projects.split(',') if p.strip()]
        project_list = [p for p in project_list_default if p in requested]
    elif args.project:
        project_list = [p for p in project_list_default if p == args.project]
    else:
        project_list = project_list_default
    if not project_list:
        logging.error('No valid projects resolved from arguments; exiting')
        return

    username = os.environ.get('JIRA_USERNAME') or config.get('jira_username') or 'jjkli@consoleconnect.com'
    api_token = os.environ.get('JIRA_API_TOKEN') or config.get('jira_api_token')
    if not api_token:
        logging.error('Missing jira_api_token in config.json')
        return
    auth = (username, api_token)

    # Process each project sequentially
    for project in project_list:
        ok, sc, msg = preflight_validate_project(auth, project, jira_url)
        if not ok:
            logging.error(f'Preflight failed project "{project}" status={sc} detail={msg}; skipping')
            log_pipeline_run(None, pipeline_name=PIPELINE_NAME, run_id=run_id, level='ERROR', message=f'Preflight failed {project}: {msg}', status='ERROR')
            continue
        logging.info(f"Starting backfill for project {project}")
        log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='INFO', message=f'Starting backfill for project {project}', status='RUNNING')
        last_completed_start = None
        while True:
            # Determine next window for this project
            window_start = None
            window_end = None
            q_next = f"SELECT WindowStart, WindowEnd FROM `{dataset_id}.{progress_table}` WHERE Project = @project AND Status NOT IN ('complete','degraded') ORDER BY WindowStart ASC LIMIT 1"
            job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter('project', 'STRING', project)])
            try:
                res = client.query(q_next, job_config=job_config).result()
                for row in res:
                    window_start = row.WindowStart
                    window_end = row.WindowEnd
                    break
            except Exception as e:
                logging.warning(f"Progress query failed for project {project}: {e}")

            adaptive_days = window_days  # default 7-day window
            # Adaptive sizing using recent history (last up to 5 complete windows)
            try:
                hist_q = f"""
                    SELECT RowCount, WindowStart, WindowEnd, IFNULL(Search429,0) AS Search429, IFNULL(History429,0) AS History429
                    FROM `{dataset_id}.{progress_table}`
                    WHERE Project=@project AND Status IN ('complete','degraded')
                    ORDER BY WindowEnd DESC
                    LIMIT 5
                """
                hist_cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter('project','STRING',project)])
                hist = list(client.query(hist_q, job_config=hist_cfg).result())
                if hist:
                    last = hist[0]
                    last_count = last.RowCount or 0
                    # Compute last window span hours
                    try:
                        span_sec = (last.WindowEnd - last.WindowStart).total_seconds()
                        last_hours = max(0.01, span_sec / 3600.0)
                    except Exception:
                        last_hours = window_days * 24
                    base_hours = window_days * 24
                    min_hours = MIN_SHRINK_HOURS
                    candidate_hours = last_hours

                    # Shrink rules (multiplicative / halving toward thresholds)
                    # Rate-limit driven shrink has precedence
                    last_search_429 = getattr(last, 'Search429', 0) or 0
                    last_history_429 = getattr(last, 'History429', 0) or 0
                    if (last_history_429 >= RATE_SHRINK_HISTORY_429) or (last_search_429 >= RATE_SHRINK_SEARCH_429):
                        candidate_hours = max(min_hours, last_hours * RATE_SHRINK_FACTOR)
                    elif last_count > ADAPT_HIGH_ROWS and last_hours > min_hours:
                        candidate_hours = max(min_hours, last_hours / 2.0)
                    elif last_count > ADAPT_MEDIUM_ROWS and last_hours > 12:
                        # soften shrink for medium spike
                        candidate_hours = max(12, last_hours / 1.5)
                    else:
                        # Potential expansion back toward base if consistently low AND we are currently below base
                        if last_hours < base_hours:
                            # look at most recent ADAPT_GROW_CONSECUTIVE windows
                            recent = hist[:ADAPT_GROW_CONSECUTIVE]
                            if len(recent) == ADAPT_GROW_CONSECUTIVE:
                                if all((r.RowCount or 0) < ADAPT_LOW_ROWS for r in recent):
                                    candidate_hours = min(base_hours, last_hours * 2.0)

                    # Final clamp
                    candidate_hours = max(min_hours, min(candidate_hours, base_hours))
                    adaptive_days = candidate_hours / 24.0
            except Exception as e:
                logging.debug(f"Adaptive sizing query failed for {project}: {e}")

            if window_start and window_end:
                candidate_end = window_end  # existing in-progress slice; do not alter span (will clamp later)
            else:
                latest_end = None
                q_latest = f"SELECT WindowEnd FROM `{dataset_id}.{progress_table}` WHERE Project = @project ORDER BY WindowEnd DESC LIMIT 1"
                try:
                    res = client.query(q_latest, job_config=job_config).result()
                    for row in res:
                        latest_end = row.WindowEnd
                        break
                except Exception as e:
                    logging.warning(f"Latest window query failed for project {project}: {e}")
                # Overlap if possible when we have a previous completed/degraded window
                if latest_end:
                    overlap = timedelta(minutes=OVERLAP_MINUTES)
                    # Normalize inputs to naive
                    latest_end_naive = latest_end.replace(tzinfo=None) if getattr(latest_end, 'tzinfo', None) else latest_end
                    last_completed_naive = last_completed_start.replace(tzinfo=None) if (last_completed_start and getattr(last_completed_start, 'tzinfo', None)) else last_completed_start
                    candidate_start = latest_end_naive - overlap
                    # If repeating or going backwards, drop overlap
                    if last_completed_naive and candidate_start <= last_completed_naive:
                        candidate_start = latest_end_naive
                    # If prior span already short (<=2*overlap) skip overlap
                    if last_completed_naive and (latest_end_naive - last_completed_naive) <= overlap * 2:
                        candidate_start = latest_end_naive
                    norm_min_ts = min_ts.replace(tzinfo=None) if getattr(min_ts, 'tzinfo', None) else min_ts
                    if candidate_start < norm_min_ts:
                        candidate_start = norm_min_ts
                    window_start = candidate_start
                else:
                    window_start = min_ts
                candidate_end = window_start + timedelta(days=adaptive_days)

            ws_naive = window_start.replace(tzinfo=None) if getattr(window_start, 'tzinfo', None) else window_start
            now_naive = now.replace(tzinfo=None) if getattr(now, 'tzinfo', None) else now
            candidate_end_naive = candidate_end.replace(tzinfo=None) if getattr(candidate_end, 'tzinfo', None) else candidate_end
            window_end = min(candidate_end_naive, now_naive)

            # Check if window is too small (less than minimum threshold)
            window_span_minutes = (window_end - ws_naive).total_seconds() / 60
            if window_span_minutes < MIN_WINDOW_MINUTES:
                logging.info(f"Window for {project} is too small ({window_span_minutes:.1f} minutes < {MIN_WINDOW_MINUTES} minutes); moving to next project")
                break

            # Guard: clamp any oversized existing window (e.g., legacy 1-year row) down to configured window_days
            span_days = (window_end - ws_naive).days + ((window_end - ws_naive).seconds/86400)
            max_span = window_days
            if span_days > max_span + 0.01:  # allow minor rounding
                # Update progress row to split into proper day-sized window, then continue loop to re-select
                try:
                    new_end = ws_naive + timedelta(days=window_days)
                    adjust = f"""
                        UPDATE `{dataset_id}.{progress_table}`
                        SET WindowEnd = TIMESTAMP('{new_end}')
                        WHERE Project='{project}' AND Status!='complete'
                          AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive}') AS STRING)
                          AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{window_end}') AS STRING)
                    """
                    client.query(adjust).result()
                    logging.info(f"Clamped oversized window for {project} from span {span_days:.2f}d to {window_days}d; re-evaluating")
                    continue
                except Exception as e:
                    logging.warning(f"Failed to clamp oversized window for {project}: {e}; aborting project")
                    break

            if ws_naive >= now_naive:
                logging.info(f"Backfill complete for project {project}; no further windows (ws >= now)")
                break

            project_clause = f'project = "{project}"' if ' ' in project or '&' in project else f'project = {project}'
            jql_query = f"({project_clause}) AND updated >= \"{ws_naive.strftime('%Y/%m/%d %H:%M')}\" AND updated < \"{window_end.strftime('%Y/%m/%d %H:%M')}\""

            # Mark window in_progress
            try:
                merge = f"""
                    MERGE `{dataset_id}.{progress_table}` T
                    USING (SELECT TIMESTAMP('{ws_naive}') AS WindowStart, TIMESTAMP('{window_end}') AS WindowEnd, '{project}' AS Project) S
                    ON T.WindowStart = S.WindowStart AND T.WindowEnd = S.WindowEnd AND T.Project = S.Project
                    WHEN MATCHED THEN UPDATE SET Status='in_progress', LastRun=CURRENT_TIMESTAMP(), Project=S.Project
                    WHEN NOT MATCHED THEN INSERT (WindowStart, WindowEnd, Status, LastRun, Project)
                    VALUES (S.WindowStart, S.WindowEnd, 'in_progress', CURRENT_TIMESTAMP(), S.Project)
                """
                client.query(merge).result()
                logging.info(f"Project {project} window {ws_naive} -> {window_end} marked in_progress")
            except Exception as e:
                logging.warning(f"Could not mark window in_progress for project {project}: {e}")
                break

            log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='INFO', message='Window in_progress', status='RUNNING', window_start=ws_naive.strftime('%Y-%m-%d %H:%M:%S'), window_end=window_end.strftime('%Y-%m-%d %H:%M:%S'))
            success = False
            row_count = 0
            # reset per-window counters
            global SEARCH_429_COUNT, HISTORY_429_COUNT
            SEARCH_429_COUNT = 0
            HISTORY_429_COUNT = 0
            try:
                success, row_count = sync_changelog_window(jira_url, jql_query, auth, client, dataset_id, table_id, ws_naive, window_end)
            except Exception as e:
                logging.exception(f"Window sync fatal error for {project}: {e}")
                log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='ERROR', message=f'Window sync failed {project}: {e}', status='ERROR')

            if success:
                # Determine degraded vs complete
                failed_histories = 0
                total_histories = 0
                try:
                    # Estimate by counting distinct History_ID inserted this window (optional heavier query omitted). Use counters instead.
                    pass
                except Exception:
                    pass
                # If high rate-limits or failures proportionally, degrade
                degraded = False
                # Approximate failure ratio using HISTORY_429_COUNT relative to issues processed if available
                try:
                    issues_processed = client.query(
                        f"SELECT COUNT(DISTINCT Issue_Key) c FROM `{dataset_id}.{table_id}` WHERE SyncTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)"  # heuristic
                    ).result()
                    # Not strictly needed; rely on threshold constants
                except Exception:
                    pass
                if (HISTORY_429_COUNT > 0 or SEARCH_429_COUNT > 0):
                    # We don't have exact failed issue count here; degraded if any remaining history gaps exceed threshold.
                    # Simpler rule: if history 429s proportionally > 0 and row_count > 0 and HISTORY_429_COUNT / max(1,row_count) > FAILURE_RATIO_DEGRADED -> degrade
                    ratio = HISTORY_429_COUNT / max(1, row_count)
                    if ratio > FAILURE_RATIO_DEGRADED:
                        degraded = True
                status_final = 'degraded' if degraded else 'complete'
                try:
                    upd = f"""
                        UPDATE `{dataset_id}.{progress_table}`
                        SET Status='{status_final}', LastRun=CURRENT_TIMESTAMP(), Project='{project}', RowCount={row_count},
                            Search429={SEARCH_429_COUNT}, History429={HISTORY_429_COUNT}
                        WHERE CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive}') AS STRING)
                          AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{window_end}') AS STRING)
                          AND Project='{project}'
                          AND Status!='complete'
                    """
                    client.query(upd).result()
                    logging.info(f"Project {project} window {ws_naive}->{window_end} {status_final} rows={row_count} 429_search={SEARCH_429_COUNT} 429_history={HISTORY_429_COUNT}")
                    log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='INFO', message=f'Window {status_final} {project}', status='SUCCESS', window_start=ws_naive.strftime('%Y-%m-%d %H:%M:%S'), window_end=window_end.strftime('%Y-%m-%d %H:%M:%S'), rows_merged=int(row_count))
                    if status_final in ('complete','degraded'):
                        last_completed_start = ws_naive
                    # Dynamic concurrency scaling
                    global CURRENT_HISTORY_WORKERS, _NO429_STREAK
                    if HISTORY_429_COUNT > 0 or SEARCH_429_COUNT > 0:
                        # scale down immediately
                        CURRENT_HISTORY_WORKERS = max(HISTORY_MIN_WORKERS, int(CURRENT_HISTORY_WORKERS * HISTORY_SCALE_DOWN_FACTOR))
                        _NO429_STREAK = 0
                        logging.info(f"Scaling down history workers to {CURRENT_HISTORY_WORKERS} due to 429s")
                    else:
                        _NO429_STREAK += 1
                        if _NO429_STREAK >= HISTORY_SCALE_UP_NO429_WINDOWS and CURRENT_HISTORY_WORKERS < HISTORY_MAX_WORKERS:
                            CURRENT_HISTORY_WORKERS = min(HISTORY_MAX_WORKERS, max(CURRENT_HISTORY_WORKERS + 1, int(CURRENT_HISTORY_WORKERS * HISTORY_SCALE_UP_FACTOR)))
                            _NO429_STREAK = 0
                            logging.info(f"Scaling up history workers to {CURRENT_HISTORY_WORKERS} (no 429 streak)")
                except Exception as e:
                    logging.warning(f"Failed to mark window {status_final} for {project}: {e}")
            else:
                try:
                    fail = f"""
                        UPDATE `{dataset_id}.{progress_table}`
                        SET Status='failed', LastRun=CURRENT_TIMESTAMP(), Project='{project}', RowCount={row_count},
                            Search429={SEARCH_429_COUNT}, History429={HISTORY_429_COUNT}
                        WHERE CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive}') AS STRING)
                          AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{window_end}') AS STRING)
                          AND Project='{project}'
                          AND Status!='complete'
                    """
                    client.query(fail).result()
                    logging.info(f"Project {project} window {ws_naive}->{window_end} failed rows={row_count}")
                    log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='ERROR', message=f'Window failed {project} rows={row_count}', status='ERROR', window_start=ws_naive.strftime('%Y-%m-%d %H:%M:%S'), window_end=window_end.strftime('%Y-%m-%d %H:%M:%S'), rows_merged=int(row_count))
                except Exception as e:
                    logging.warning(f"Failed to mark window failed for {project}: {e}")

            if not success:
                # Incremental shrink strategy (Option B): reduce span and retry until MIN_SHRINK_HOURS; if already minimal -> mark degraded and break
                try:
                    current_span_hours = (window_end - ws_naive).total_seconds() / 3600.0
                except Exception:
                    current_span_hours = 0
                if current_span_hours > (MIN_SHRINK_HOURS + 0.05):
                    new_span_hours = max(MIN_SHRINK_HOURS, current_span_hours * RATE_SHRINK_FACTOR)
                    new_end = ws_naive + timedelta(hours=new_span_hours)
                    try:
                        adjust_fail = f"""
                            UPDATE `{dataset_id}.{progress_table}`
                            SET WindowEnd = TIMESTAMP('{new_end}'), Status='failed'
                            WHERE Project='{project}'
                              AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive}') AS STRING)
                              AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{window_end}') AS STRING)
                        """
                        client.query(adjust_fail).result()
                        logging.info(f"Shrinking failed window for {project} from {current_span_hours:.2f}h -> {new_span_hours:.2f}h; will retry")
                        # continue loop to pick up adjusted (failed) window again
                        continue
                    except Exception as e:
                        logging.warning(f"Could not shrink failed window for {project}: {e}; breaking")
                        break
                else:
                    # Already at minimal span; mark degraded to allow progress and break
                    try:
                        degrade = f"""
                            UPDATE `{dataset_id}.{progress_table}`
                            SET Status='degraded', LastRun=CURRENT_TIMESTAMP()
                            WHERE Project='{project}'
                              AND CAST(WindowStart AS STRING)=CAST(TIMESTAMP('{ws_naive}') AS STRING)
                              AND CAST(WindowEnd AS STRING)=CAST(TIMESTAMP('{window_end}') AS STRING)
                              AND Status='failed'
                        """
                        client.query(degrade).result()
                        logging.info(f"Marking minimal failed window as degraded for {project} {ws_naive}->{window_end}; moving on")
                    except Exception as e:
                        logging.warning(f"Failed to mark minimal window degraded for {project}: {e}")
                    break

            # Continue loop to process next window

    log_pipeline_run(client, pipeline_name=PIPELINE_NAME, run_id=run_id, level='INFO', message='Pipeline finished (all projects processed)', status='SUCCESS')

if __name__ == '__main__':
    main()