"""
Cloud Function: Jira Comments Sync
Syncs Jira comments from consoleconnect.atlassian.net to BigQuery.
Routes through VPC to access Jira behind VPN.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import logging
import uuid
import time
import random
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, secretmanager
import functions_framework

# Import shared helper functions from local copy
from jira_helpers import (
    load_base_jql,
    build_jql,
    convert_timestamp,
    create_or_replace_temp_table,
    delete_temp_table,
    wait_for_table,
    insert_rows_with_retry,
    table_exists,
    execute_bq_query_with_retry,
)
from logging_config import setup_root_logging
from pipeline_runs_logger import log_pipeline_run

# Setup logging
setup_root_logging()

# Jitter used when sleeping after 429s
JITTER_MAX_SECONDS = 0.3

# Rate limiting settings (Jira Cloud: ~180 req/min = ~3 req/sec)
JIRA_RATE_LIMIT_PAUSE_SEC = 0.4  # Pause between paginated searches


def handle_429_backoff(response, attempt=1, max_attempts=3):
    """Handle 429 rate limit with exponential backoff."""
    if response.status_code != 429 or attempt >= max_attempts:
        return False
    retry_after = int(response.headers.get("Retry-After", 30) or 30)
    backoff_time = min(retry_after * (2 ** (attempt - 1)), 120)  # Cap at 2 minutes
    wait_time = backoff_time + random.uniform(0, JITTER_MAX_SECONDS)
    logging.warning(
        f"429 Rate limit (attempt {attempt}/{max_attempts}). Waiting {wait_time:.1f}s"
    )
    time.sleep(wait_time)
    return True


def create_session_with_retries():
    """Create a requests Session with connection pooling and retry strategy."""
    session = requests.Session()

    # Configure retry strategy for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # exponential backoff: 1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    # Apply to both http and https
    adapter = HTTPAdapter(
        max_retries=retry_strategy, pool_connections=30, pool_maxsize=30
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def insert_rows_resilient(
    client, dataset_id, temp_table_id, rows, bq_schema, max_attempts=3
):
    """Insert rows with resilience: retry, and recreate temp table if needed."""
    if not rows:
        return True
    for attempt in range(max_attempts):
        # Try the standard insert with retries
        if insert_rows_with_retry(
            client, dataset_id, temp_table_id, rows, bq_schema, retries=5, delay=3
        ):
            return True

        # If insert failed, check if table exists; if not, recreate and wait
        try:
            if not table_exists(client, dataset_id, temp_table_id):
                logging.warning(
                    f"Temp table missing after failed insert attempt {attempt + 1}/{max_attempts}. Recreating..."
                )
                if create_or_replace_temp_table(
                    client, dataset_id, temp_table_id, bq_schema
                ):
                    if wait_for_table(
                        client, dataset_id, temp_table_id, retries=15, delay=1
                    ):
                        if insert_rows_with_retry(
                            client,
                            dataset_id,
                            temp_table_id,
                            rows,
                            bq_schema,
                            retries=5,
                            delay=3,
                        ):
                            return True
        except Exception as e:
            logging.warning(f"Error during resilient insert attempt: {e}")

        if attempt < max_attempts - 1:
            time.sleep(2 * (1.5**attempt))

    logging.error(f"Failed to insert rows after {max_attempts} resilient attempts")
    return False


def get_secret(secret_id, project_id="pccw-internal-virtual-agent"):
    """Retrieve a secret, falling back to the newest enabled version if the latest alias is destroyed."""
    client = secretmanager.SecretManagerServiceClient()
    secret_path = f"projects/{project_id}/secrets/{secret_id}"
    latest_name = f"{secret_path}/versions/latest"

    try:
        response = client.access_secret_version(request={"name": latest_name})
        return response.payload.data.decode("UTF-8")
    except Exception as exc:
        logging.warning(
            f"Latest secret alias failed for {secret_id}: {exc}. Trying newest enabled version."
        )

    try:
        versions = list(client.list_secret_versions(request={"parent": secret_path}))
        valid = []
        for version in versions:
            state = getattr(version, "state", None)
            state_name = (
                getattr(state, "name", str(state)).lower() if state is not None else ""
            )
            if state_name in {"enabled", "state.enabled"}:
                version_num = int(version.name.rsplit("/", 1)[-1])
                valid.append((version_num, version.name))
        if valid:
            _, chosen_name = max(valid, key=lambda item: item[0])
            response = client.access_secret_version(request={"name": chosen_name})
            return response.payload.data.decode("UTF-8")
    except Exception as fallback_exc:
        logging.error(
            f"Failed to recover fallback secret for {secret_id}: {fallback_exc}"
        )

    raise


def load_config():
    """Load Jira config from Secret Manager instead of config.json."""
    try:
        api_token = get_secret("jira-api-token")
        user_email = get_secret("jira-user-email")
        return {"jira_api_token": api_token, "jira_user": user_email}
    except Exception as e:
        logging.error(f"Failed to load config from Secret Manager: {e}")
        return None


def body_to_string(body):
    """Convert ADF (Atlassian Document Format) body to plain text."""
    if not body:
        return None

    try:
        if isinstance(body, str):
            body_dict = json.loads(body)
        else:
            body_dict = body

        def extract_text(node):
            if not node:
                return ""
            if isinstance(node, str):
                return node
            if isinstance(node, dict):
                text_parts = []
                if "text" in node:
                    text_parts.append(str(node["text"]))
                if "content" in node and isinstance(node["content"], list):
                    for child in node["content"]:
                        text_parts.append(extract_text(child))
                return "".join(text_parts)
            if isinstance(node, list):
                return "".join([extract_text(item) for item in node])
            return str(node)

        return extract_text(body_dict)
    except Exception as e:
        logging.warning(f"Error parsing ADF body: {e}")
        return None


def fetch_comments_for_issue(issue_key, username, api_token, session):
    """Fetch all comments for a single issue using pagination."""
    url = f"https://consoleconnect.atlassian.net/rest/api/3/issue/{issue_key}/comment"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (username, api_token)
    params = {"startAt": 0, "maxResults": 75}

    all_comments = []
    try:
        while True:
            try:
                resp = session.get(
                    url, headers=headers, auth=auth, params=params, timeout=30
                )
                if resp.status_code == 429:
                    ra = int(resp.headers.get("Retry-After", 30) or 30)
                    logging.warning(
                        f"429 on comments fetch for {issue_key}; sleeping {ra}s"
                    )
                    time.sleep(ra + random.uniform(0, JITTER_MAX_SECONDS))
                    continue
                resp.raise_for_status()
                data = resp.json()
                comments = data.get("comments", [])
                all_comments.extend(comments)
                if len(comments) < params["maxResults"]:
                    break
                params["startAt"] += len(comments)
            except requests.exceptions.Timeout:
                logging.warning(
                    f"Timeout fetching comments for {issue_key}; continuing"
                )
                break
    except Exception as e:
        logging.warning(f"Error fetching comments for {issue_key}: {e}")

    return all_comments


def fetch_comments_batch(issue_keys, username, api_token, session, max_workers=16):
    """Fetch comments for multiple issues in parallel."""
    comments_by_issue = {}
    try:
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(issue_keys))
        ) as executor:
            future_map = {
                executor.submit(
                    fetch_comments_for_issue, key, username, api_token, session
                ): key
                for key in issue_keys
            }
            for future in as_completed(future_map):
                issue_key = future_map[future]
                try:
                    comments_by_issue[issue_key] = future.result()
                except Exception as e:
                    logging.warning(f"Failed to fetch comments for {issue_key}: {e}")
                    comments_by_issue[issue_key] = []
    except Exception as e:
        logging.error(f"Error in fetch_comments_batch: {e}")

    return comments_by_issue


def fetch_and_sync_jira_comments():
    """Main sync function - same logic as local script."""
    config = load_config()
    if config is None:
        return

    jira_url = "https://consoleconnect.atlassian.net/rest/api/3/search/jql"
    username = config.get("jira_user", "jjkli@consoleconnect.com")
    api_token = config.get("jira_api_token")

    table_id = "JiraComments"
    temp_table_id = "JiraComments_temp"
    pipeline_name = "GCP - JiraComments"

    run_id = str(uuid.uuid4())
    client = None

    try:
        run_started = datetime.now(timezone.utc)

        # Use UAT project for BigQuery where GSO dataset exists
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        dataset_id = "GSO"

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline started",
            status="RUNNING",
        )

        # Load base JQL
        base_default = (
            "("
            'project = "GS&O Data Analytics" OR '
            'project = "Customer Success Management" OR '
            'project = "GS&O Tool Automation" OR '
            'project = "GS&O Knowledge Consolidation" OR '
            "project = TAC OR "
            'project = "VOICE - CE" OR '
            'project = "IOT CE" OR '
            'project = "Console Application Support" OR '
            'project = "Console Connect Provisioning" OR '
            'project = "Global Service Delivery Team" OR '
            'project = "Transmission TX-CE" OR '
            'project = "Mobility SMS - CE" OR '
            'project = "Managed Security Services" OR '
            "project = Sherbet OR "
            'project = "Google Contact Center AI Solution" OR '
            'project = "QMS Documentation" OR '
            'project = "Operational Case Reviews" OR '
            'project = "IT Helpdesk" OR '
            'project = "Vendor Verification Team" OR '
            "project = IPECR OR "
            "project = IPCE OR "
            'project = "Internal Knowledge Management" OR '
            "project = ITOPS OR "
            'project = "GS&O Strategic Initiatives" '
            ")"
        )
        base_jql = load_base_jql(default_text=base_default)
        logging.info(f"Resolved base_jql: {base_jql}")

        if not base_jql:
            # Log and mark pipeline as ERROR before exiting
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="No base JQL resolved",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return

        lookback_minutes = 15

        # Optimized single-pass approach: capture any recent activity with a small safety overlap.
        jql_any_activity = build_jql(
            base_jql,
            f"(updated >= -{lookback_minutes}m OR resolutiondate >= -{lookback_minutes}m OR comment.updated >= -{lookback_minutes}m)",
            joiner="AND",
        )
        logging.info(
            f"JQL (any activity in last {lookback_minutes}m): {jql_any_activity}"
        )

        # BigQuery schema
        bq_schema = [
            bigquery.SchemaField("Issue_Key", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Comment_ID", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("Author_Account_ID", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Author_Display_Name", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Created", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Updated", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("Body", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Visibility_Type", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("Visibility_Value", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("SyncTime", "TIMESTAMP", mode="NULLABLE"),
        ]

        rows_to_insert = []
        issue_keys_total = set()

        def generate_rows(issue_key, comments):
            """Generator for comment rows."""
            window_start_utc = (
                run_started - timedelta(minutes=lookback_minutes)
            ).replace(tzinfo=timezone.utc)
            for comment in comments:
                # Discard comments that haven't been touched in the current target window.
                updated_str = convert_timestamp(
                    comment.get("updated") or comment.get("created")
                )
                if updated_str:
                    updated_dt = datetime.strptime(
                        updated_str, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if updated_dt < window_start_utc:
                        continue

                visibility = comment.get("visibility", {})
                row = {
                    "Issue_Key": issue_key,
                    "Comment_ID": comment.get("id"),
                    "Author_Account_ID": comment.get("author", {}).get("accountId"),
                    "Author_Display_Name": comment.get("author", {}).get("displayName"),
                    "Created": convert_timestamp(comment.get("created")),
                    "Updated": convert_timestamp(comment.get("updated")),
                    "Body": body_to_string(comment.get("body")),
                    "Visibility_Type": visibility.get("type"),
                    "Visibility_Value": visibility.get("value"),
                    "SyncTime": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                }
                yield row

        # Create persistent session with connection pooling
        session = create_session_with_retries()

        def search_issue_keys_paginated(jql: str, label: str):
            """Fetch ALL matching issue keys with pagination. CRITICAL: Prevents data loss!"""
            all_keys = []
            start_at = 0
            max_results = 100
            headers_local = {"Accept": "application/json"}
            auth_local = (username, api_token)
            attempt = 0
            max_attempts = 3

            while True:
                params_local = {
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": max_results,
                    "fields": "key",
                }
                try:
                    resp = session.get(
                        jira_url,
                        headers=headers_local,
                        auth=auth_local,
                        params=params_local,
                        timeout=60,
                    )

                    if resp.status_code == 429:
                        if handle_429_backoff(resp, attempt + 1, max_attempts):
                            attempt += 1
                            continue
                        else:
                            logging.error(
                                f"Failed after {max_attempts} 429 attempts on {label}"
                            )
                            break

                    resp.raise_for_status()
                    attempt = 0  # Reset on success

                    # Detect silent Jira auth failure (returns 200 with empty results)
                    login_reason = resp.headers.get("x-seraph-loginreason", "")
                    if (
                        "AUTHENTICATED_FAILED" in login_reason
                        or "AUTHENTICATION_DENIED" in login_reason
                    ):
                        logging.error(
                            f"Jira auth FAILED for {label} (x-seraph-loginreason: {login_reason}). API token may be expired or revoked. Update 'jira-api-token' secret."
                        )
                        break

                    data_local = resp.json()
                    issues_local = data_local.get("issues", [])
                    if not issues_local:
                        break

                    all_keys.extend(
                        [i.get("key") for i in issues_local if i.get("key")]
                    )
                    total = data_local.get("total", 0)

                    if start_at + max_results >= total:
                        break

                    start_at += max_results
                    time.sleep(JIRA_RATE_LIMIT_PAUSE_SEC)  # Respect rate limits

                except requests.exceptions.Timeout:
                    logging.warning(
                        f"Timeout fetching keys for {label} at startAt={start_at}"
                    )
                    break
                except Exception as e:
                    logging.error(f"Error fetching keys for {label}: {e}")
                    break

            logging.info(
                f"{label}: Fetched {len(all_keys)} total issue keys (paginated)"
            )
            return all_keys

        # Search for issues with recent activity - now WITH PAGINATION
        all_issue_keys = search_issue_keys_paginated(
            jql_any_activity, "comments_activity"
        )
        try:
            data = {"issues": [{"key": k} for k in all_issue_keys]}
            issues = data.get("issues", [])
            for issue in issues:
                issue_keys_total.add(issue.get("key"))
            logging.info(f"Comments search fetched {len(issue_keys_total)} issue keys")
        except Exception as e:
            logging.error(f"Comments search error: {e}")
            return

        if not issue_keys_total:
            logging.info("No issues found with recent comments")
            window_start_dt = run_started - timedelta(minutes=lookback_minutes)
            window_end_dt = run_started
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="INFO",
                message="Pipeline finished (no data)",
                status="SUCCESS",
                window_start=window_start_dt,
                window_end=window_end_dt,
                rows_merged=0,
                duration_seconds=duration_seconds,
            )
            return

        # Fetch comments in parallel (session already created above)
        issue_key_list = list(issue_keys_total)
        comments_by_issue = fetch_comments_batch(
            issue_key_list, username, api_token, session, max_workers=8
        )

        # Close session to release connections
        session.close()

        comments_count = 0
        for issue_key, comments in comments_by_issue.items():
            for row in generate_rows(issue_key, comments):
                rows_to_insert.append(row)
                comments_count += 1

        logging.info(f"Fetched {comments_count} total comments")

        if not rows_to_insert:
            logging.info("No comments found for recently changed issues")
            window_start_dt = run_started - timedelta(minutes=lookback_minutes)
            window_end_dt = run_started
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="INFO",
                message="Pipeline finished (no data)",
                status="SUCCESS",
                window_start=window_start_dt,
                window_end=window_end_dt,
                rows_merged=0,
                duration_seconds=duration_seconds,
            )
            return

        if not create_or_replace_temp_table(
            client, dataset_id, temp_table_id, bq_schema
        ):
            logging.error("Setup failed: Could not create temp table.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Could not create temp table",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return
        if not wait_for_table(client, dataset_id, temp_table_id):
            logging.error("Setup failed: Temp table not available.")
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message="Temp table not available",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            return

        if rows_to_insert:
            if not insert_rows_resilient(
                client,
                dataset_id,
                temp_table_id,
                rows_to_insert,
                bq_schema,
                max_attempts=4,
            ):
                logging.error(
                    "Failed to insert rows into temp table after resilient attempts."
                )
                delete_temp_table(client, dataset_id, temp_table_id)
                return

        # Merge temp table into final table
        try:
            merge_query = f"""
                MERGE `{dataset_id}.{table_id}` T
                USING `{dataset_id}.{temp_table_id}` S
                ON T.Issue_Key = S.Issue_Key AND T.Comment_ID = S.Comment_ID
                WHEN MATCHED THEN UPDATE SET
                    T.Author_Account_ID = S.Author_Account_ID,
                    T.Author_Display_Name = S.Author_Display_Name,
                    T.Created = S.Created,
                    T.Updated = S.Updated,
                    T.Body = S.Body,
                    T.Visibility_Type = S.Visibility_Type,
                    T.Visibility_Value = S.Visibility_Value,
                    T.SyncTime = S.SyncTime
                WHEN NOT MATCHED THEN INSERT (Issue_Key, Comment_ID, Author_Account_ID, Author_Display_Name, Created, Updated, Body, Visibility_Type, Visibility_Value, SyncTime)
                VALUES (S.Issue_Key, S.Comment_ID, S.Author_Account_ID, S.Author_Display_Name, S.Created, S.Updated, S.Body, S.Visibility_Type, S.Visibility_Value, S.SyncTime)
            """
            execute_bq_query_with_retry(
                client, merge_query, max_retries=5, initial_delay=10.0
            )
            logging.info(f"Merged temp table into '{dataset_id}.{table_id}'.")
        except Exception as e:
            logging.error(f"Error merging temp table: {e}")
            delete_temp_table(client, dataset_id, temp_table_id)
            run_ended = datetime.now(timezone.utc)
            duration_seconds = (run_ended - run_started).total_seconds()
            log_pipeline_run(
                client,
                pipeline_name=pipeline_name,
                run_id=run_id,
                level="ERROR",
                message=f"MERGE failed: {e}",
                status="ERROR",
                duration_seconds=duration_seconds,
            )
            raise

        delete_temp_table(client, dataset_id, temp_table_id)

        # Log pipeline end
        window_start_dt = run_started - timedelta(minutes=lookback_minutes)
        window_end_dt = run_started
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="INFO",
            message="Pipeline finished",
            status="SUCCESS",
            window_start=window_start_dt,
            window_end=window_end_dt,
            rows_merged=comments_count,
            duration_seconds=duration_seconds,
        )
    except Exception as e:
        run_ended = datetime.now(timezone.utc)
        duration_seconds = (run_ended - run_started).total_seconds()

        log_pipeline_run(
            client,
            pipeline_name=pipeline_name,
            run_id=run_id,
            level="ERROR",
            message=f"Exception: {e}",
            status="ERROR",
            error_code=getattr(e, "code", None),
            duration_seconds=duration_seconds,
        )
        raise


@functions_framework.http
def main(request):
    """Cloud Function HTTP entry point."""
    # Cleanup: Mark stale RUNNING entries as ERROR (older than 10 minutes)
    try:
        client = bigquery.Client(project="pccw-internal-virt-agent-uat")
        cleanup_query = """
            UPDATE `GSO.PipelineRuns`
            SET Status = 'ERROR', Message = 'Function timeout or crash (auto-cleaned)'
            WHERE PipelineName = 'GCP - JiraComments'
            AND Status = 'RUNNING'
            AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
        """
        client.query(cleanup_query).result()
    except Exception as e:
        logging.warning(f"Failed to cleanup stale RUNNING entries: {e}")

    try:
        fetch_and_sync_jira_comments()
        return {"status": "success", "message": "Jira comments sync completed"}, 200
    except Exception as e:
        error_msg = f"Cloud Function failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        return {"status": "error", "message": str(e)}, 500
