"""Backfill ONLY the `Creator` column for a Jira project in GSO.JiraTickets.

Fetches Creator (displayName) for the project's issues directly from the Jira API
(the same way the JiraTickets / JiraTicketsNightly datapipes do: `fields.creator.displayName`),
then MERGEs those values into BigQuery updating ONLY the Creator column.

Only rows matching the project are touched (BQ Project value + Key prefix); every
other column is left intact.

Idempotent / resumable:
  * Fetch step skips chunks already recorded in <label>_done.txt.
  * Merge step is a WHEN MATCHED UPDATE of Creator only, safe to re-run.

Usage:
  python backfill_creator.py --dryrun                                          # sample only
  python backfill_creator.py --project "IP Customer Engineering" --prefix IPCE --label creator --dryrun
  python backfill_creator.py --project "Transmission TX-CE" --prefix TXCE --label creator_txce --fetch-only
  python backfill_creator.py --project "Transmission TX-CE" --prefix TXCE --label creator_txce
"""
import json, os, sys, time
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client
from google.cloud import bigquery

DIR = r"g:\My Drive\Scripts\Temp\ipce_backfill"
AUTH_B64 = open(os.path.join(DIR, "auth.txt")).read().strip()

PROJECT = "pccw-internal-virt-agent-uat"
DATASET = "GSO"
TABLE = "JiraTickets"
TARGET = f"{PROJECT}.{DATASET}.{TABLE}"

# Per-project settings (overridable via CLI args --project / --prefix / --label).
PROJECT_VALUE = "IP Customer Engineering"   # BQ Project value to target rows
KEY_PREFIX = "IPCE"                          # key prefix, e.g. IPCE / TXCE
LABEL = "creator"                            # output file label (creator.jsonl etc.)

BASE = "https://consoleconnect.atlassian.net/rest/api/3"
OUT = os.path.join(DIR, f"{LABEL}.jsonl")
DONE = os.path.join(DIR, f"{LABEL}_done.txt")
LOG = os.path.join(DIR, f"{LABEL}.log")
TMP = f"{DATASET}.{LABEL}_backfill_tmp"

CHUNK = 200         # keys per Jira search request
MAX_RESULTS = 100   # Jira search page size
SLEEP = 0.05        # polite delay between requests


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def get_field_value(field):
    """Match datapipe JiraTickets.get_field_value: dict -> value/name/displayName."""
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get('value') or field.get('name') or field.get('displayName')
    if isinstance(field, list):
        return ', '.join(str(item.get('value') or item.get('name') or item.get('displayName'))
                         if isinstance(item, dict) else item for item in field)
    if isinstance(field, bool):
        return str(field)
    return str(field)


def build_session():
    s = requests.Session()
    retry = Retry(total=6, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
    return s

def search_creator(session, keys):
    """Query Jira for creators of a chunk of keys; return {key: creatorDisplayName}.

    Uses GET /rest/api/3/search/jql with jql/startAt/maxResults/fields params,
    mirroring the JiraTicketsNightly datapipe's search_issues().
    """
    keys_jql = ', '.join(f'"{k}"' for k in keys if k)
    if not keys_jql:
        return {}
    jql = f"key in ({keys_jql})"
    result = {}
    start_at = 0
    while True:
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": MAX_RESULTS,
            "fields": "key,creator",
        }
        resp = session.get(
            BASE + "/search/jql",
            headers={"Authorization": "Basic " + AUTH_B64,
                     "Accept": "application/json"},
            params=params, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        for issue in data.get("issues", []):
            fields = issue.get("fields", {}) or {}
            creator = get_field_value(fields.get("creator"))
            result[issue.get("key")] = creator
        total = data.get("total", 0)
        start_at += len(data.get("issues", []))
        if start_at >= total or not data.get("issues"):
            break
    return result


def ipce_keys_from_bq(client):
    """Return the target-projection keys currently in the table (only these get updated)."""
    rows = client.query(
        f"SELECT DISTINCT Key FROM `{TARGET}` "
        f"WHERE Project = @proj AND Key LIKE '{KEY_PREFIX}-%' AND Key IS NOT NULL AND TRIM(Key) <> '' ",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("proj", "STRING", PROJECT_VALUE)]),
    ).result()
    return sorted({r.Key for r in rows if getattr(r, "Key", None)})


def fetch_creators(client):
    keys = ipce_keys_from_bq(client)
    log(f"{KEY_PREFIX} keys in BQ: {len(keys)}")
    done = set()
    if os.path.exists(DONE):
        with open(DONE, "r", encoding="utf-8") as f:
            done = {ln.strip() for ln in f if ln.strip()}

    chunks = [keys[i:i + CHUNK] for i in range(0, len(keys), CHUNK)]
    session = build_session()
    fetched = 0
    for ci, chunk in enumerate(chunks, 1):
        marker = chunk[0]  # leader key used as the resumable checkpoint
        if marker in done:
            continue
        creators = search_creator(session, chunk)
        with open(OUT, "a", encoding="utf-8") as f:
            for k in chunk:
                f.write(json.dumps({"Key": k, "Creator": creators.get(k)}, ensure_ascii=False) + "\n")
        with open(DONE, "a", encoding="utf-8") as f:
            f.write(marker + "\n")
        fetched += len(chunk)
        if ci % 25 == 0:
            log(f"progress {ci}/{len(chunks)} chunks, {fetched} keys written")
        time.sleep(SLEEP)
    log(f"fetch complete: {fetched} newly written this run")
    print(f"FETCH DONE newly_written={fetched} total_keys={len(keys)}")



def load_and_merge():
    if not os.path.exists(OUT) or os.path.getsize(OUT) == 0:
        print("no creator.jsonl found; nothing to merge")
        return

    client = get_client(PROJECT)
    tmp = TMP
    schema = [
        bigquery.SchemaField("Key", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("Creator", "STRING", mode="NULLABLE"),
    ]

    # Drop duplicates keeping the latest record per key (last write wins).
    cleaned = OUT + ".clean"
    seen = {}
    with open(OUT, encoding="utf-8") as f, open(cleaned, "w", encoding="utf-8") as o:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            seen[rec.get("Key")] = rec.get("Creator")
        for k, c in seen.items():
            o.write(json.dumps({"Key": k, "Creator": c}, ensure_ascii=False) + "\n")

    client.delete_table(f"{PROJECT}.{tmp}", not_found_ok=True)
    with open(cleaned, "rb") as fh:
        load_job = client.load_table_from_file(
            fh, f"{PROJECT}.{tmp}",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.job.SourceFormat.NEWLINE_DELIMITED_JSON,
                schema=schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
        load_job.result()
    loaded = load_job.output_rows
    print(f"temp rows loaded: {loaded}")

    merge_sql = f"""
        MERGE `{TARGET}` T
        USING (
            SELECT DISTINCT Key, Creator FROM `{PROJECT}.{tmp}`
            WHERE Key LIKE '{KEY_PREFIX}-%'
        ) S
        ON T.Key = S.Key
        WHEN MATCHED THEN UPDATE SET T.Creator = S.Creator
    """
    client.query(merge_sql).result()
    print("merge done (Creator-only update)")

    # verify remaining nulls
    r = list(client.query(
        f"SELECT COUNT(*) AS n, "
        f"SUM(CASE WHEN Creator IS NULL THEN 1 ELSE 0 END) AS still_null "
        f"FROM `{TARGET}` WHERE Project = @p AND Key LIKE '{KEY_PREFIX}-%'",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("p", "STRING", PROJECT_VALUE)]),
    ).result())[0]
    print(f"{KEY_PREFIX} rows total={r.n} still missing Creator={r.still_null}")

    try:
        os.remove(cleaned)
    except Exception:
        pass
    client.delete_table(f"{PROJECT}.{tmp}", not_found_ok=True)


def dryrun():
    client = get_client(PROJECT)
    keys = ipce_keys_from_bq(client)
    print(f"total {KEY_PREFIX} keys in BQ: {len(keys)}")
    session = build_session()
    creators = search_creator(session, keys[:CHUNK])
    for k in keys[:10]:
        print(f"{k} -> {creators.get(k)}")
    print(f"sample chunk fetched: {len(creators)}")


def _set_project(project_value, key_prefix, label):
    """Set per-project globals before running (defaults are IPCE)."""
    global PROJECT_VALUE, KEY_PREFIX, LABEL, OUT, DONE, LOG, TMP
    PROJECT_VALUE = project_value
    KEY_PREFIX = key_prefix
    LABEL = label
    OUT = os.path.join(DIR, f"{LABEL}.jsonl")
    DONE = os.path.join(DIR, f"{LABEL}_done.txt")
    LOG = os.path.join(DIR, f"{LABEL}.log")
    TMP = f"{DATASET}.{LABEL}_backfill_tmp"


def _get_arg(args, name, default):
    for i, a in enumerate(args):
        if a == name:
            return args[i + 1] if i + 1 < len(args) else default
    return default


def main():
    args = sys.argv[1:]
    project_value = _get_arg(args, "--project", PROJECT_VALUE)
    key_prefix = _get_arg(args, "--prefix", KEY_PREFIX)
    label = _get_arg(args, "--label", LABEL)
    _set_project(project_value, key_prefix, label)

    client = get_client(PROJECT)
    if "--dryrun" in args:
        dryrun()
        return 0
    fetch_creators(client)
    if "--fetch-only" in args:
        return 0
    load_and_merge()
    return 0


if __name__ == "__main__":
    sys.exit(main())

