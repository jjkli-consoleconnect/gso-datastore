"""Bounded Jira fetching and durable, atomic nightly batch checkpoints."""

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Iterator, TypeVar

import requests
from google.api_core.exceptions import BadRequest, Conflict
from google.cloud import bigquery

T = TypeVar("T")


class RunPaused(Exception):
    """The invocation budget is exhausted; resume from the saved checkpoint."""


class RunBudget:
    def __init__(self, seconds: float = 1200):
        if seconds <= 120 or seconds > 1500:
            raise ValueError("Nightly budget must be between 120 and 1500 seconds")
        self.deadline = time.monotonic() + seconds

    def check(self, reserve: float = 90) -> None:
        if time.monotonic() + reserve >= self.deadline:
            raise RunPaused("Invocation budget reached; saved batches will resume")

    def sleep(self, seconds: float) -> None:
        self.check(seconds + 90)
        time.sleep(seconds)


def bounded_fetch(
    fetch: Callable[[str], T], keys: Iterable[str], workers: int
) -> Iterator[tuple[str, T]]:
    """Keep retained responses bounded by worker count, not by issue count."""
    if workers < 1:
        raise ValueError("workers must be positive")
    keys_iter = iter(keys)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for key in keys_iter:
            pending[executor.submit(fetch, key)] = key
            if len(pending) == workers:
                break
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in ready:
                key = pending.pop(future)
                result = future.result()
                yield key, result
                del result
                del future
                next_key = next(keys_iter, None)
                if next_key is not None:
                    pending[executor.submit(fetch, next_key)] = next_key


class JiraReader:
    def __init__(self, headers: dict, auth: tuple, budget: RunBudget):
        self.headers = headers
        self.auth = auth
        self.budget = budget
        self.local = threading.local()
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.cooldown = 0.0
        self.interval = float(os.environ.get("NIGHTLY_REQUEST_INTERVAL_SECONDS", "0.5"))
        if self.interval <= 0:
            raise ValueError("Nightly request interval must be positive")

    def _wait(self) -> None:
        while True:
            self.budget.check()
            with self.lock:
                now = time.monotonic()
                delay = max(self.cooldown, self.next_request) - now
                if delay <= 0:
                    self.next_request = now + self.interval
                    return
            self.budget.sleep(min(delay, 1.0))

    def get(self, url: str, *, params: dict, **unused) -> requests.Response:
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
        for attempt in range(5):
            self._wait()
            try:
                response = self.local.session.get(
                    url, headers=self.headers, auth=self.auth,
                    params=params, timeout=(10, 30),
                )
            except requests.RequestException as exc:
                if attempt == 4:
                    raise
                logging.warning("Jira connection failed (attempt %s/5): %s", attempt + 1, exc)
                self.budget.sleep(2 ** (attempt + 1))
                continue
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "30")
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = (
                        parsedate_to_datetime(retry_after)
                        - datetime.now(timezone.utc)
                    ).total_seconds()
                delay = max(delay, 1.0) + 1.0
                response.close()
                with self.lock:
                    self.cooldown = max(self.cooldown, time.monotonic() + delay)
                logging.warning("Jira 429: shared worker cooldown %.1fs (attempt %s/5)", delay, attempt + 1)
                if attempt == 4:
                    raise RuntimeError("Jira rate-limit retries exhausted; batch remains pending")
                self.budget.sleep(delay)
                continue
            if response.status_code >= 500 and attempt < 4:
                logging.warning("Jira HTTP %s; retrying attempt %s/5", response.status_code, attempt + 1)
                response.close()
                self.budget.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("Jira retries exhausted")


class WindowCheckpoint:
    def __init__(self, client, dataset: str, progress_table: str, project: str, start, end):
        self.client = client
        self.table = f"{client.project}.{dataset}.{progress_table}_batches"
        self.params = [
            bigquery.ScalarQueryParameter("project", "STRING", project),
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
        ]
        self.where = "Project=@project AND WindowStart=@start AND WindowEnd=@end"
        self.keys = None
        self.offset = 0
        self.row_count = 0
        rows = self._query(f"SELECT IssueKeys, NextIndex, RowCount FROM `{self.table}` WHERE {self.where}")
        for row in rows:
            self.keys = list(row.IssueKeys)
            self.offset = int(row.NextIndex)
            self.row_count = int(row.RowCount)
        if self.keys is not None and not 0 <= self.offset <= len(self.keys):
            raise RuntimeError("Invalid nightly checkpoint offset")

    @staticmethod
    def ensure_table(client, dataset: str, progress_table: str) -> None:
        client.query(
            f"CREATE TABLE IF NOT EXISTS `{client.project}.{dataset}.{progress_table}_batches` "
            "(Project STRING, WindowStart TIMESTAMP, WindowEnd TIMESTAMP, "
            "IssueKeys ARRAY<STRING>, NextIndex INT64, RowCount INT64, LastRun TIMESTAMP)"
        ).result()

    def _query(self, sql: str, extra=()):
        return self.client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=self.params + list(extra))
        ).result()

    def initialize(self, keys: list[str]) -> None:
        keys = list(dict.fromkeys(keys))
        self._query(
            f"MERGE `{self.table}` T USING "
            "(SELECT @project Project, @start WindowStart, @end WindowEnd) S "
            "ON T.Project=S.Project AND T.WindowStart=S.WindowStart AND T.WindowEnd=S.WindowEnd "
            "WHEN NOT MATCHED THEN INSERT "
            "(Project,WindowStart,WindowEnd,IssueKeys,NextIndex,RowCount,LastRun) "
            "VALUES (@project,@start,@end,@keys,0,0,CURRENT_TIMESTAMP())",
            [bigquery.ArrayQueryParameter("keys", "STRING", keys)],
        )
        # Reload in case another invocation initialized the same snapshot.
        for row in self._query(f"SELECT IssueKeys, NextIndex, RowCount FROM `{self.table}` WHERE {self.where}"):
            self.keys = list(row.IssueKeys)
            self.offset = int(row.NextIndex)
            self.row_count = int(row.RowCount)
        if self.keys is None:
            raise RuntimeError("Checkpoint initialization did not persist")

    def batches(self, budget: RunBudget) -> Iterator[list[str]]:
        size = int(os.environ.get("NIGHTLY_BATCH_ISSUES", "100"))
        if not 1 <= size <= 500:
            raise ValueError("NIGHTLY_BATCH_ISSUES must be between 1 and 500")
        if self.keys is None:
            raise RuntimeError("Issue snapshot has not been initialized")
        while self.offset < len(self.keys):
            budget.check()
            old_offset = self.offset
            yield self.keys[self.offset:self.offset + size]
            if self.offset <= old_offset:
                raise RuntimeError("Batch was not durably committed")

    def commit(self, merge: str, temp_table: str, count: int, rows: int) -> None:
        next_index = self.offset + count
        if self.keys is None or next_index > len(self.keys):
            raise ValueError("Batch exceeds checkpoint snapshot")
        sql = f"""
        BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*)=1 FROM `{self.table}`
                WHERE {self.where} AND NextIndex=@old_index)
          AS 'Checkpoint advanced concurrently';
        {merge};
        UPDATE `{self.table}` SET NextIndex=@next_index,
          RowCount=RowCount+@rows, LastRun=CURRENT_TIMESTAMP()
          WHERE {self.where};
        TRUNCATE TABLE `{temp_table}`;
        COMMIT TRANSACTION;
        """
        parameters = [
            bigquery.ScalarQueryParameter("old_index", "INT64", self.offset),
            bigquery.ScalarQueryParameter("next_index", "INT64", next_index),
            bigquery.ScalarQueryParameter("rows", "INT64", rows),
        ]
        for attempt in range(5):
            try:
                self._query(sql, parameters)
                break
            except (BadRequest, Conflict) as exc:
                if "concurrent update" not in str(exc).lower() or attempt == 4:
                    raise
                delay = 5 * (2 ** attempt)
                logging.warning(
                    "Batch transaction conflicted with another writer; retry %s/5 in %ss",
                    attempt + 1, delay,
                )
                time.sleep(delay)
        self.offset = next_index
        self.row_count += rows
        logging.info("Batch checkpoint saved: %s/%s issues, %s rows", self.offset, len(self.keys), self.row_count)


def load_staging_rows(client, dataset: str, table: str, rows: list, schema: list) -> bool:
    if rows:
        config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND")
        client.load_table_from_json(
            rows, f"{client.project}.{dataset}.{table}", job_config=config
        ).result()
    return True


def has_pending_work(client, progress_table: str, pipeline_name: str) -> bool:
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("pipeline", "STRING", pipeline_name),
    ])
    sql = f"""
    WITH latest AS (
      SELECT Status, RunTime FROM `{client.project}.GSO.PipelineRuns`
      WHERE PipelineName=@pipeline ORDER BY RunTime DESC LIMIT 1
    ), upstream AS (
      SELECT Status FROM `{client.project}.GSO.PipelineRuns`
      WHERE PipelineName='GCP - JiraChangelogsNightly'
      ORDER BY RunTime DESC LIMIT 1
    )
    SELECT COALESCE((SELECT
      (Status='PAUSED'
       OR (Status IN ('ERROR','RUNNING')
           AND RunTime < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
           AND EXISTS(SELECT 1 FROM `{client.project}.GSO.{progress_table}`
                      WHERE Status NOT IN ('complete','degraded'))))
      FROM latest), FALSE)
      AND (@pipeline != 'GCP - JiraCommentsNightly'
           OR COALESCE((SELECT Status='SUCCESS' FROM upstream), FALSE)) AS pending
    """
    return bool(next(iter(client.query(sql, job_config=config).result())).pending)
