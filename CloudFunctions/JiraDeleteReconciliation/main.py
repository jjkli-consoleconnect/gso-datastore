"""
Cloud Function: Jira Delete Reconciliation
===========================================
Weekly reconciliation that identifies Jira tickets which no longer exist in
Jira and marks them soft-deleted in BigQuery.

WHY THIS EXISTS
---------------
Jira's JQL search API is *eventually consistent* -- after a ticket is deleted
it can still appear in search results for minutes, and the result set can also
be silently truncated (100 per page without error).  Using JQL to derive a
"full active keyset" for diff-based deletion is therefore fundamentally
unreliable.

ALGORITHM
---------
For each project:

  1. Candidate selection:
      Pull keys from BQ where IsDeleted = FALSE and Key is non-empty.
      If STALE_DAYS > 0, additionally require SyncTime older than STALE_DAYS.
      If STALE_DAYS <= 0, staleness filtering is disabled.

  2. Batch existence prefilter (dramatically reduces individual API calls):
     Chunk candidates into groups of BATCH_SIZE.  One search call per batch:
       JQL: issuekey in (KEY-1, KEY-2, ..., KEY-N)
     Keys returned by Jira = confirmed to exist → skip.
     Keys absent from the response = possibly deleted → proceed to step 3.
     On batch API error → all chunk keys fall through to step 3
     (conservative: never lose a deletion candidate on ambiguity).

  3. Direct per-key verification of possibly-deleted candidates (strongly
     consistent):
     For each candidate key, call GET /rest/api/3/issue/{key}.
       200  ---  still exists; leave as-is.
       404  ---  confirmed deleted; soft-delete in BQ.
       429  ---  rate-limited; sleep Retry-After and retry.
       other error  ---  skip conservatively (do NOT delete).

  4. Apply BQ update using parameterised ARRAY query (no string interpolation
     of key values --- no SQL-injection risk).

SAFETY GATES (layered)
----------------------
  --- Per-key 404 proof required before any deletion (strongly consistent
      direct-issue API, bypasses the search index entirely).
  --- Any ambiguous API error --- skip; never delete on doubt.
  --- Batch prefilter falls back conservatively on any error (routes chunk
      to per-key check, never silently drops candidates).
  --- MAX_CANDIDATES_PER_PROJECT cap (default 500) per run.
  --- DRY_RUN mode: log intent but apply no BQ changes.

ENVIRONMENT VARIABLES
---------------------
  DRY_RUN                    "true" --- log only, no BQ updates  (default: false)
    STALE_DAYS                 Min days since last SyncTime to qualify as
                                                         candidate; set 0 to disable       (default: 90)
  MAX_CANDIDATES_PER_PROJECT Safety cap on candidates checked   (default: 500)
  BATCH_SIZE                 Keys per issuekey-in batch check   (default: 100)
  RATE_LIMIT_PER_SEC         Token-bucket rate for Jira calls   (default: 30)
  CONCURRENT_REQUESTS        ThreadPoolExecutor max workers     (default: 10)
  SINGLE_PROJECT / PROJECTS  Scope to one or comma-list of projects

SAFETY GATES (layered)
----------------------
  See the SAFETY GATES block below — same as existing, except the circuit
  breaker is now documented here too:
  --- Circuit breaker: if ≥ CIRCUIT_BREAKER_SKIP_THRESHOLD of the first
      CIRCUIT_BREAKER_MIN_CHECKS per-key results are "skip" (timeout/error),
      the project is aborted immediately.  This prevents a single Jira-
      unresponsive project from consuming the entire Cloud Run timeout and
      blocking all subsequent projects.
"""

import logging
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import functions_framework
import requests
from google.cloud import bigquery, secretmanager

from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

setup_root_logging()

# ------ Constants ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

JIRA_BASE_URL = "https://consoleconnect.atlassian.net"
JIRA_SEARCH_URL = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
JIRA_ISSUE_URL_TEMPLATE = f"{JIRA_BASE_URL}/rest/api/3/issue/{{key}}"

BQ_PROJECT = "pccw-internal-virt-agent-uat"
BQ_DATASET = "GSO"
BQ_TABLE = "JiraTickets"

PIPELINE_NAME = "GCP - JiraDeleteReconciliation"
GCP_PROJECT = "pccw-internal-virtual-agent"

JITTER_MAX_SECONDS = 0.5

# ------ Runtime configuration (override via env vars) ------------------------------------------------------------------------------------

DRY_RUN: bool = os.environ.get("DRY_RUN", "").strip().lower() == "true"
STALE_DAYS: int = int(os.environ.get("STALE_DAYS", "90"))
MAX_CANDIDATES_PER_PROJECT: int = int(os.environ.get("MAX_CANDIDATES_PER_PROJECT", "500"))
BATCH_SIZE: int = int(os.environ.get("BATCH_SIZE", "100"))
RATE_LIMIT_PER_SEC: float = float(os.environ.get("RATE_LIMIT_PER_SEC", "30"))
CONCURRENT_REQUESTS: int = int(os.environ.get("CONCURRENT_REQUESTS", "10"))

# Circuit breaker: abort per-key loop if Jira is consistently unresponsive
CIRCUIT_BREAKER_MIN_CHECKS: int = 10        # minimum results before evaluating
CIRCUIT_BREAKER_SKIP_THRESHOLD: float = 0.80  # trip if ≥80% are skips

# ------ Project scope (matches JiraTicketsNightly) ---------------------------------------------------------------------------------------------

DEFAULT_PROJECTS = [
    "GS&O Data Analytics",
    "Customer Success Management",
    "GS&O Tool Automation",
    "GS&O Knowledge Consolidation",
    "TAC",
    "VOICE - CE",
    "IOT CE",
    "Console Application Support",
    "Console Connect Provisioning",
    "Global Service Delivery Team",
    "Transmission TX-CE",
    "Mobility SMS - CE",
    "Managed Security Services",
    "Sherbet",
    "Google Contact Center AI Solution",
    "QMS Documentation",
    "Operational Case Reviews",
    "IT Helpdesk",
    "GS&O Strategic Initiatives",
]


# ------ Thread-safe token bucket ---------------------------------------------------------------------------------------------------------------------------------------------------

class TokenBucket:
    """Thread-safe token bucket for API rate limiting."""

    def __init__(self, rate_per_sec: float) -> None:
        self._rate = rate_per_sec
        self._tokens = float(rate_per_sec)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, amount: float = 1.0) -> None:
        """Block until `amount` tokens are available, then consume them."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
            time.sleep(0.02)


def check_key_exists(
    key: str,
    auth: tuple,
    max_retries: int = 5,
    abort_event: threading.Event | None = None,
) -> str:
    """
    Strongly-consistent single-key existence check via the Jira issue API.

    Returns one of three strings:
      "exists"   HTTP 200  --- ticket is present and accessible.
      "deleted"  HTTP 404  --- ticket does not exist (or no permission; treated
                             as deleted when the API account has full access).
      "skip"     Any other outcome --- conservative: do NOT soft-delete.

    abort_event: when set (e.g. by the circuit breaker), exits between retry
    attempts rather than completing all max_retries.
    """
    url = JIRA_ISSUE_URL_TEMPLATE.format(key=key)
    headers = {"Accept": "application/json"}
    params = {"fields": "key"}
    delay = 1.0

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=20)

            if resp.status_code == 200:
                return "exists"

            if resp.status_code == 404:
                return "deleted"

            if resp.status_code == 429:
                ra = min(int(resp.headers.get("Retry-After", 30) or 30), 120)
                logging.warning(
                    f"429 on key {key} (attempt {attempt+1}/{max_retries}); "
                    f"sleeping {ra}s"
                )
                time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                continue  # retry without consuming the attempt counter

            # 400, 401, 403, 5xx --- ambiguous or auth error --- skip
            logging.warning(
                f"HTTP {resp.status_code} for key {key}; skipping (conservative)"
            )
            return "skip"

        except requests.exceptions.Timeout:
            logging.warning(f"Timeout on key {key} (attempt {attempt+1}/{max_retries})")
        except Exception as exc:
            logging.warning(f"Error on key {key} (attempt {attempt+1}/{max_retries}): {exc}")

        if attempt < max_retries - 1:
            if abort_event and abort_event.is_set():
                return "skip"  # circuit breaker: exit before next retry
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

    logging.warning(f"All {max_retries} attempts exhausted for key {key}; skipping")
    return "skip"


def batch_check_keys_exist(
    keys: list[str],
    auth: tuple,
    bucket: TokenBucket,
    batch_size: int = BATCH_SIZE,
) -> tuple[set[str], set[str]]:
    """
    Batch-check key existence using JQL ``issuekey in (K1, K2, ...)``.

    Sends one POST /rest/api/3/search/jql request per chunk of ``batch_size``
    keys.  Keys present in the Jira response are confirmed to exist; keys
    absent from the response are *possibly* deleted and must be verified
    individually via :func:`check_key_exists`.

    On any API error the entire failing chunk is routed to ``possibly_deleted``
    so that per-key confirmation still runs --- conservative by design.

    Returns:
        (confirmed_exist, possibly_deleted) --- two disjoint sets covering
        every key in ``keys``.
    """
    confirmed_exist: set[str] = set()
    possibly_deleted: set[str] = set()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    for i in range(0, len(keys), batch_size):
        chunk = keys[i : i + batch_size]
        bucket.take()
        jql = f"issuekey in ({', '.join(chunk)})"
        payload = {"jql": jql, "fields": ["key"], "maxResults": len(chunk)}

        try:
            resp = requests.post(
                JIRA_SEARCH_URL, headers=headers, auth=auth, json=payload, timeout=30
            )

            if resp.status_code == 429:
                ra = min(int(resp.headers.get("Retry-After", 30) or 30), 120)
                logging.warning(
                    f"429 on batch check (chunk {i // batch_size + 1}); sleeping {ra}s"
                )
                time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                resp = requests.post(
                    JIRA_SEARCH_URL, headers=headers, auth=auth, json=payload, timeout=30
                )

            if resp.status_code == 200:
                returned = {issue["key"] for issue in resp.json().get("issues", [])}
                for k in chunk:
                    if k in returned:
                        confirmed_exist.add(k)
                    else:
                        possibly_deleted.add(k)
            else:
                logging.warning(
                    f"Batch check got HTTP {resp.status_code} for chunk of {len(chunk)} keys; "
                    "routing all to per-key verification"
                )
                possibly_deleted.update(chunk)

        except Exception as exc:
            logging.warning(
                f"Batch check error ({exc}); routing {len(chunk)} keys to per-key verification"
            )
            possibly_deleted.update(chunk)

    return confirmed_exist, possibly_deleted


def get_stale_candidate_keys(
    client: bigquery.Client,
    dataset: str,
    table: str,
    project: str,
    stale_days: int,
    max_candidates: int,
) -> list[str]:
    """
        Return candidate BQ keys for the given project that:
            --- are not already soft-deleted,
            --- have non-empty Key values,
            --- and if stale_days > 0, have not been synced in the last
                    `stale_days` days.

    Ordered by SyncTime ASC (oldest first) so the stalest tickets are checked
    first. Capped at `max_candidates` to limit API call volume per run.
    """
    rows = list(
        client.query(
            f"""
            SELECT Key
            FROM `{dataset}.{table}`
            WHERE Project = @proj
              AND COALESCE(IsDeleted, FALSE) = FALSE
              AND TRIM(COALESCE(Key, '')) <> ''
              AND (
                  @stale_days <= 0
                  OR SyncTime IS NULL
                  OR SyncTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @stale_days DAY)
                  )
            ORDER BY SyncTime ASC
            LIMIT @max_candidates
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("proj", "STRING", project),
                    bigquery.ScalarQueryParameter("stale_days", "INT64", stale_days),
                    bigquery.ScalarQueryParameter("max_candidates", "INT64", max_candidates),
                ]
            ),
        ).result()
    )
    return [r.Key for r in rows]


def apply_soft_deletes_bq(
    client: bigquery.Client,
    dataset: str,
    table: str,
    keys_to_delete: list[str],
    dry_run: bool = False,
) -> int:
    """
    Soft-delete a list of confirmed-missing keys in BQ.

    Uses a parameterised ARRAY query (UNNEST(@keys)) to avoid any risk of
    SQL-injection from issue key values.

    Returns the number of rows actually updated (0 in dry-run mode).
    """
    if not keys_to_delete:
        return 0

    preview = keys_to_delete[:10]
    ellipsis = "..." if len(keys_to_delete) > 10 else ""
    logging.info(
        f"{'[DRY RUN] Would soft-delete' if dry_run else 'Soft-deleting'} "
        f"{len(keys_to_delete)} key(s): {preview}{ellipsis}"
    )

    if dry_run:
        return 0

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("keys", "STRING", keys_to_delete)
        ]
    )
    client.query(
        f"""
        UPDATE `{dataset}.{table}`
        SET IsDeleted = TRUE,
            DeletedAt = CURRENT_TIMESTAMP()
        WHERE Key IN UNNEST(@keys)
          AND COALESCE(IsDeleted, FALSE) = FALSE
        """,
        job_config=job_config,
    ).result()

    return len(keys_to_delete)


# ------ Per-project orchestration ---------------------------------------------------------------------------------------------------------------------------------------------------

def reconcile_project(
    project: str,
    auth: tuple,
    client: bigquery.Client,
    bucket: TokenBucket,
    dry_run: bool = DRY_RUN,
    stale_days: int = STALE_DAYS,
    max_candidates: int = MAX_CANDIDATES_PER_PROJECT,
    concurrent_requests: int = CONCURRENT_REQUESTS,
) -> dict:
    """
    Run the full reconciliation cycle for a single project.

    Returns a stats dict:
      {
        "project":           str,
        "status":            "ok" | "no_candidates",
        "candidates":        int,
        "checked":           int,
        "confirmed_deleted": int,
        "skipped_on_error":  int,
        "soft_deleted_bq":   int,
      }
    """
    stats: dict = {
        "project": project,
        "status": "ok",
        "candidates": 0,
        "checked": 0,
        "confirmed_deleted": 0,
        "skipped_on_error": 0,
        "soft_deleted_bq": 0,
    }

    logging.info(f"--------------- [{project}] Starting reconciliation ---------------")

    # ------ Step 1: Get stale candidates ------------------------------------------------------------------------------------------------------------------
    candidate_keys = get_stale_candidate_keys(
        client, BQ_DATASET, BQ_TABLE, project, stale_days, max_candidates
    )
    stats["candidates"] = len(candidate_keys)

    if not candidate_keys:
        logging.info(
            f"[{project}] No stale candidates "
            f"(all active tickets synced within the last {stale_days} days)"
        )
        stats["status"] = "no_candidates"
        return stats

    if stale_days > 0:
        logging.info(
            f"[{project}] Checking {len(candidate_keys)} stale candidate(s) "
            f"(SyncTime > {stale_days} days ago)"
        )
    else:
        logging.info(
            f"[{project}] Checking {len(candidate_keys)} candidate(s) "
            "(staleness filter disabled)"
        )

    # ------ Step 2: Batch existence prefilter -------------------------------------------------------------------------------------------------------------------
    # One JQL call per BATCH_SIZE keys: issuekey in (K1, K2, ...).
    # Keys returned by Jira are confirmed to exist; only absent keys need
    # expensive per-key GET verification.  Dramatically reduces API call
    # volume and eliminates most timeout-retry chains.
    confirmed_exist_batch, possibly_deleted = batch_check_keys_exist(
        candidate_keys, auth, bucket=bucket
    )
    logging.info(
        f"[{project}] Batch prefilter: {len(confirmed_exist_batch)} confirmed exist, "
        f"{len(possibly_deleted)} need per-key check"
    )

    # ------ Step 3: Per-key verification of possibly-deleted candidates -------------------------------------------------------------------------------------
    keys_to_delete: list[str] = []
    keys_still_exist: list[str] = list(confirmed_exist_batch)
    keys_skipped: list[str] = []

    circuit_tripped = threading.Event()

    def _verify(key: str) -> tuple[str, str]:
        if circuit_tripped.is_set():
            return key, "skip"  # fast return — no HTTP call
        bucket.take()  # honour rate limit
        return key, check_key_exists(key, auth, abort_event=circuit_tripped)

    with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
        futures = {executor.submit(_verify, k): k for k in possibly_deleted}
        for fut in as_completed(futures):
            key, outcome = fut.result()
            stats["checked"] += 1

            if outcome == "deleted":
                keys_to_delete.append(key)
                logging.info(f"[{project}] 404 CONFIRMED DELETED: {key}")
            elif outcome == "exists":
                keys_still_exist.append(key)
                logging.debug(f"[{project}] 200 still exists: {key}")
            else:
                keys_skipped.append(key)
                logging.warning(f"[{project}] SKIP (ambiguous/error): {key}")

            # Circuit breaker: abort project if Jira is consistently unresponsive
            if (
                not circuit_tripped.is_set()
                and stats["checked"] >= CIRCUIT_BREAKER_MIN_CHECKS
                and len(keys_skipped) / stats["checked"] >= CIRCUIT_BREAKER_SKIP_THRESHOLD
            ):
                logging.warning(
                    f"[{project}] Circuit breaker tripped: "
                    f"{len(keys_skipped)/stats['checked']:.0%} skip rate after "
                    f"{stats['checked']} checks — remaining keys will be skipped"
                )
                circuit_tripped.set()

    stats["checked"] += len(confirmed_exist_batch)
    stats["confirmed_deleted"] = len(keys_to_delete)
    stats["skipped_on_error"] = len(keys_skipped)

    if circuit_tripped.is_set():
        logging.warning(
            f"[{project}] Aborting after circuit breaker trip — "
            f"0 soft-deletes applied to protect data integrity"
        )
        stats["status"] = "skipped_high_error_rate"
        return stats

    logging.info(
        f"[{project}] Verification complete --- "
        f"confirmed_deleted={len(keys_to_delete)}, "
        f"still_exist={len(keys_still_exist)}, "
        f"skipped_on_error={len(keys_skipped)}"
    )

    # ------ Step 4: Apply BQ soft-deletes ---------------------------------------------------------------------------------------------------------------
    deleted_count = apply_soft_deletes_bq(
        client, BQ_DATASET, BQ_TABLE, keys_to_delete, dry_run=dry_run
    )
    stats["soft_deleted_bq"] = deleted_count

    return stats


# ------ Main orchestration ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def run_reconciliation(dry_run_override: bool | None = None) -> None:
    run_id = str(uuid.uuid4())
    run_started = datetime.now(timezone.utc)
    client: bigquery.Client | None = None
    effective_dry_run = DRY_RUN if dry_run_override is None else dry_run_override

    try:
        # ------ Credentials ---------------------------------------------------------------------------------------------------------------------------------------------------------
        sm_client = secretmanager.SecretManagerServiceClient()

        def _get_secret(secret_id: str) -> str:
            name = f"projects/{GCP_PROJECT}/secrets/{secret_id}/versions/latest"
            return sm_client.access_secret_version(
                request={"name": name}
            ).payload.data.decode("UTF-8")

        api_token = _get_secret("jira-api-token")
        user_email = _get_secret("jira-user-email")
        auth = (user_email, api_token)

        client = bigquery.Client(project=BQ_PROJECT)

        log_pipeline_run(
            client,
            pipeline_name=PIPELINE_NAME,
            run_id=run_id,
            level="INFO",
            message=(
                f"Reconciliation started --- "
                f"dry_run={effective_dry_run}, stale_days={STALE_DAYS}, "
                f"max_candidates_per_project={MAX_CANDIDATES_PER_PROJECT}"
            ),
            status="RUNNING",
        )

        # ------ Project scope ---------------------------------------------------------------------------------------------------------------------------------------------------
        projects = DEFAULT_PROJECTS
        env_single = os.environ.get("SINGLE_PROJECT") or os.environ.get("PROJECT")
        env_projects_str = os.environ.get("PROJECTS")
        if env_single:
            projects = [env_single.strip()]
        elif env_projects_str:
            projects = [p.strip() for p in env_projects_str.split(",") if p.strip()]

        logging.info(f"Project scope ({len(projects)}): {projects}")
        if effective_dry_run:
            logging.warning("DRY RUN mode enabled --- no BQ changes will be written")

        # ------ Shared rate limiter ---------------------------------------------------------------------------------------------------------------------------------
        bucket = TokenBucket(RATE_LIMIT_PER_SEC)

        # ------ Per-project loop ------------------------------------------------------------------------------------------------------------------------------------------
        all_stats: list[dict] = []
        for proj in projects:
            proj_stats = reconcile_project(
                project=proj,
                auth=auth,
                client=client,
                bucket=bucket,
                dry_run=effective_dry_run,
            )
            all_stats.append(proj_stats)

        # ------ Aggregate summary ---------------------------------------------------------------------------------------------------------------------------------------
        total_checked = sum(s["checked"] for s in all_stats)
        total_deleted_bq = sum(s["soft_deleted_bq"] for s in all_stats)
        total_confirmed_deleted = sum(s["confirmed_deleted"] for s in all_stats)
        total_skipped_on_error = sum(s["skipped_on_error"] for s in all_stats)
        skipped_projects = [s["project"] for s in all_stats
                            if s["status"] not in ("ok", "no_candidates")]

        summary_msg = (
            f"Reconciliation complete --- "
            f"projects_processed={len(projects)}, "
            f"projects_skipped={len(skipped_projects)}, "
            f"candidates_checked={total_checked}, "
            f"confirmed_deleted={total_confirmed_deleted}, "
            f"soft_deleted_bq={'(dry run) ' if effective_dry_run else ''}{total_deleted_bq}, "
            f"skipped_on_error={total_skipped_on_error}"
        )
        if skipped_projects:
            summary_msg += f"; SKIPPED PROJECTS: {', '.join(skipped_projects)}"

        logging.info(summary_msg)

        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=PIPELINE_NAME,
            run_id=run_id,
            level="WARNING" if skipped_projects else "INFO",
            message=summary_msg,
            status="SUCCESS",
            rows_merged=total_deleted_bq,
            duration_seconds=duration_seconds,
        )

    except Exception as exc:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()
        logging.exception(f"Reconciliation failed with unhandled exception: {exc}")
        if client is not None:
            try:
                log_pipeline_run(
                    client,
                    pipeline_name=PIPELINE_NAME,
                    run_id=run_id,
                    level="ERROR",
                    message=f"Unhandled exception: {exc}",
                    status="ERROR",
                    duration_seconds=duration_seconds,
                )
            except Exception:
                pass
        raise


def resolve_request_dry_run(request) -> bool | None:
    """Return request-level dry-run override when explicitly provided."""
    if request is None:
        return None

    header_value = None
    if hasattr(request, "headers") and request.headers is not None:
        header_value = request.headers.get("X-DRY-RUN")
        if header_value is None:
            header_value = request.headers.get("x-dry-run")

    if header_value is None:
        return None

    normalized = str(header_value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


# ------ Cloud Function entry point ------------------------------------------------------------------------------------------------------------------------------------------------

@functions_framework.http
def main(request):  # noqa: ANN001
    """HTTP-triggered entry point (Cloud Functions Gen2)."""
    # Stale RUNNING cleanup (same pattern as nightly functions)
    try:
        _client = bigquery.Client(project=BQ_PROJECT)
        _client.query(
            """
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR',
                Message = 'Function timeout or crash (auto-cleaned by reconcile start)'
            WHERE PipelineName = @name
              AND Status = 'RUNNING'
              AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("name", "STRING", PIPELINE_NAME)
                ]
            ),
        ).result()
    except Exception as exc:
        logging.warning(f"Stale run cleanup failed (non-fatal): {exc}")

    try:
        dry_run_override = resolve_request_dry_run(request)
        run_reconciliation(dry_run_override=dry_run_override)
        return "OK", 200
    except Exception as exc:
        logging.exception(f"Fatal error in reconciliation Cloud Function: {exc}")
        return f"ERROR: {exc}", 500

