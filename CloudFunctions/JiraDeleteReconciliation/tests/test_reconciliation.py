"""
Unit tests for JiraDeleteReconciliation/main.py

Tests are grouped by function, ordered from pure/isolated --- integrated.
Mocking strategy:
  - requests.get  ---  unittest.mock.patch
  - bigquery.Client  ---  MagicMock with chained .query().result()
  - secretmanager  ---  patched in integration tests

Run with:
    python -m pytest tests/test_reconciliation.py -v
"""

import sys
import os
import time
import threading
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Make the parent package importable without installing it.
# conftest.py inserts google.cloud stubs into sys.modules BEFORE this file
# is loaded, so main.py's "from google.cloud import bigquery, secretmanager"
# gets the lightweight fakes, and no real GCP network calls are made.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  --- loaded after conftest.py installs stubs


# ===========================================================================
# 1.  TokenBucket --- rate limiting
# ===========================================================================
class TestTokenBucket(unittest.TestCase):

    def test_first_take_is_immediate(self):
        bucket = main.TokenBucket(10)
        start = time.monotonic()
        bucket.take()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.2, "First take should return immediately")

    def test_burst_consumes_available_tokens(self):
        bucket = main.TokenBucket(5)
        # Should be able to take 5 tokens quickly (they're pre-loaded)
        for _ in range(5):
            bucket.take()
        # 6th should block briefly --- just verify it doesn't raise
        # (We can't easily assert timing in CI; just confirm no exception)
        done = threading.Event()

        def _take():
            bucket.take()
            done.set()

        t = threading.Thread(target=_take, daemon=True)
        t.start()
        t.join(timeout=2.0)
        self.assertTrue(done.is_set(), "take() should eventually return")

    def test_thread_safety(self):
        """Multiple threads taking tokens must not go below zero."""
        bucket = main.TokenBucket(100)
        results = []
        lock = threading.Lock()

        def _worker():
            bucket.take()
            with lock:
                results.append(1)

        threads = [threading.Thread(target=_worker, daemon=True) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(len(results), 20)


# ===========================================================================
# 2.  check_key_exists
# ===========================================================================
class TestCheckKeyExists(unittest.TestCase):

    def _mock_response(self, status_code, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = headers or {}
        return resp

    @patch("main.requests.get")
    def test_200_returns_exists(self, mock_get):
        mock_get.return_value = self._mock_response(200)
        self.assertEqual(main.check_key_exists("PROJ-1", ("u", "t")), "exists")

    @patch("main.requests.get")
    def test_404_returns_deleted(self, mock_get):
        mock_get.return_value = self._mock_response(404)
        self.assertEqual(main.check_key_exists("PROJ-1", ("u", "t")), "deleted")

    @patch("main.requests.get")
    def test_403_returns_skip(self, mock_get):
        mock_get.return_value = self._mock_response(403)
        self.assertEqual(main.check_key_exists("PROJ-1", ("u", "t")), "skip")

    @patch("main.requests.get")
    def test_500_returns_skip(self, mock_get):
        mock_get.return_value = self._mock_response(500)
        self.assertEqual(main.check_key_exists("PROJ-1", ("u", "t")), "skip")

    @patch("main.requests.get")
    @patch("main.time.sleep", return_value=None)
    def test_429_sleeps_then_retries_success(self, mock_sleep, mock_get):
        rate_limit = self._mock_response(429, headers={"Retry-After": "1"})
        ok = self._mock_response(200)
        mock_get.side_effect = [rate_limit, ok]
        self.assertEqual(main.check_key_exists("PROJ-1", ("u", "t"), max_retries=5), "exists")
        self.assertEqual(mock_get.call_count, 2)

    @patch("main.requests.get")
    @patch("main.time.sleep", return_value=None)
    def test_network_error_eventually_returns_skip(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("connection refused")
        result = main.check_key_exists("PROJ-1", ("u", "t"), max_retries=3)
        self.assertEqual(result, "skip")
        self.assertEqual(mock_get.call_count, 3)

    @patch("main.requests.get")
    @patch("main.time.sleep", return_value=None)
    def test_timeout_eventually_returns_skip(self, mock_sleep, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.Timeout
        result = main.check_key_exists("PROJ-1", ("u", "t"), max_retries=3)
        self.assertEqual(result, "skip")

    @patch("main.requests.get")
    def test_url_contains_key(self, mock_get):
        mock_get.return_value = self._mock_response(200)
        main.check_key_exists("GSOD-9999", ("u", "t"))
        call_url = mock_get.call_args[0][0]
        self.assertIn("GSOD-9999", call_url)

    @patch("main.requests.get")
    def test_requests_minimal_fields_only(self, mock_get):
        mock_get.return_value = self._mock_response(200)
        main.check_key_exists("PROJ-1", ("u", "t"))
        self.assertEqual(mock_get.call_args.kwargs["params"], {"fields": "key"})


# ===========================================================================
# 3.  batch_check_keys_exist
# ===========================================================================
class TestBatchCheckKeysExist(unittest.TestCase):

    def _bucket(self):
        return main.TokenBucket(1_000_000)

    def _mock_search_response(self, status_code, issues=None, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = {"issues": [{"key": k} for k in (issues or [])]}
        resp.headers = headers or {}
        return resp

    @patch("main.requests.post")
    def test_returned_keys_go_to_confirmed_exist(self, mock_post):
        mock_post.return_value = self._mock_search_response(200, issues=["PROJ-1", "PROJ-2"])
        exist, maybe_del = main.batch_check_keys_exist(
            ["PROJ-1", "PROJ-2", "PROJ-3"], ("u", "t"), self._bucket()
        )
        self.assertIn("PROJ-1", exist)
        self.assertIn("PROJ-2", exist)
        self.assertIn("PROJ-3", maybe_del)
        self.assertNotIn("PROJ-3", exist)

    @patch("main.requests.post")
    def test_all_missing_go_to_possibly_deleted(self, mock_post):
        mock_post.return_value = self._mock_search_response(200, issues=[])
        exist, maybe_del = main.batch_check_keys_exist(
            ["PROJ-1", "PROJ-2"], ("u", "t"), self._bucket()
        )
        self.assertEqual(exist, set())
        self.assertEqual(maybe_del, {"PROJ-1", "PROJ-2"})

    @patch("main.requests.post")
    def test_http_error_routes_chunk_to_possibly_deleted(self, mock_post):
        mock_post.return_value = self._mock_search_response(500)
        exist, maybe_del = main.batch_check_keys_exist(
            ["PROJ-1", "PROJ-2"], ("u", "t"), self._bucket()
        )
        self.assertEqual(exist, set())
        self.assertEqual(maybe_del, {"PROJ-1", "PROJ-2"})

    @patch("main.requests.post")
    def test_exception_routes_chunk_to_possibly_deleted(self, mock_post):
        mock_post.side_effect = Exception("network failure")
        exist, maybe_del = main.batch_check_keys_exist(
            ["PROJ-5", "PROJ-6"], ("u", "t"), self._bucket()
        )
        self.assertEqual(exist, set())
        self.assertEqual(maybe_del, {"PROJ-5", "PROJ-6"})

    @patch("main.requests.post")
    @patch("main.time.sleep", return_value=None)
    def test_429_sleeps_then_retries(self, mock_sleep, mock_post):
        rate_limited = self._mock_search_response(429, headers={"Retry-After": "1"})
        ok = self._mock_search_response(200, issues=["PROJ-1"])
        mock_post.side_effect = [rate_limited, ok]
        exist, _ = main.batch_check_keys_exist(["PROJ-1"], ("u", "t"), self._bucket())
        self.assertIn("PROJ-1", exist)
        self.assertEqual(mock_post.call_count, 2)

    @patch("main.requests.post")
    def test_batches_by_batch_size(self, mock_post):
        mock_post.return_value = self._mock_search_response(200, issues=[])
        keys = [f"PROJ-{i}" for i in range(25)]
        main.batch_check_keys_exist(keys, ("u", "t"), self._bucket(), batch_size=10)
        # 25 keys / batch_size 10 = 3 batches
        self.assertEqual(mock_post.call_count, 3)

    @patch("main.requests.post")
    def test_sets_are_disjoint_and_cover_all_keys(self, mock_post):
        mock_post.return_value = self._mock_search_response(
            200, issues=["PROJ-1", "PROJ-2"]
        )
        keys = ["PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"]
        exist, maybe_del = main.batch_check_keys_exist(keys, ("u", "t"), self._bucket())
        self.assertEqual(exist & maybe_del, set(), "sets must be disjoint")
        self.assertEqual(exist | maybe_del, set(keys), "sets must cover all keys")


# ===========================================================================
# 4.  apply_soft_deletes_bq
# ===========================================================================
class TestApplySoftDeletesBq(unittest.TestCase):

    def _make_bq_client(self):
        client = MagicMock()
        client.query.return_value.result.return_value = None
        return client

    def test_empty_list_returns_zero_without_query(self):
        client = self._make_bq_client()
        result = main.apply_soft_deletes_bq(client, "GSO", "JiraTickets", [], dry_run=False)
        self.assertEqual(result, 0)
        client.query.assert_not_called()

    def test_dry_run_logs_but_does_not_query(self):
        client = self._make_bq_client()
        result = main.apply_soft_deletes_bq(
            client, "GSO", "JiraTickets", ["PROJ-1", "PROJ-2"], dry_run=True
        )
        self.assertEqual(result, 0)
        client.query.assert_not_called()

    def test_live_run_issues_bq_query(self):
        client = self._make_bq_client()
        keys = ["PROJ-1", "PROJ-2", "PROJ-3"]
        result = main.apply_soft_deletes_bq(
            client, "GSO", "JiraTickets", keys, dry_run=False
        )
        self.assertEqual(result, 3)
        client.query.assert_called_once()
        # Verify the SQL contains UNNEST
        sql_arg = client.query.call_args[0][0]
        self.assertIn("UNNEST", sql_arg)
        self.assertIn("IsDeleted = TRUE", sql_arg)
        self.assertIn("DeletedAt", sql_arg)

    def test_parameterised_array_used_not_interpolation(self):
        """Keys must be passed as a parameterised ARRAY, not string-interpolated."""
        client = self._make_bq_client()
        tricky_key = "PROJ-1'; DROP TABLE JiraTickets; --"
        main.apply_soft_deletes_bq(
            client, "GSO", "JiraTickets", [tricky_key], dry_run=False
        )
        sql_arg = client.query.call_args[0][0]
        # The tricky key must NOT appear in the SQL string itself
        self.assertNotIn(tricky_key, sql_arg)
        # The query_parameters must contain the key
        job_config = client.query.call_args[1]["job_config"]
        param = job_config.query_parameters[0]
        self.assertIn(tricky_key, param.value)

    def test_returns_count_equal_to_keys_provided(self):
        client = self._make_bq_client()
        keys = [f"PROJ-{i}" for i in range(250)]
        result = main.apply_soft_deletes_bq(
            client, "GSO", "JiraTickets", keys, dry_run=False
        )
        self.assertEqual(result, 250)


# ===========================================================================
# 5.  get_bq_active_count --- removed (no longer needed without count gate)
# 6.  get_stale_candidate_keys
# ===========================================================================
class TestGetStaleCandidateKeys(unittest.TestCase):

    def test_returns_keys_from_bq(self):
        rows = [MagicMock(Key=f"PROJ-{i}") for i in range(5)]
        client = MagicMock()
        client.query.return_value.result.return_value = rows

        keys = main.get_stale_candidate_keys(
            client, "GSO", "JiraTickets", "TAC", stale_days=90, max_candidates=500
        )
        self.assertEqual(keys, ["PROJ-0", "PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"])

    def test_empty_result_returns_empty_list(self):
        client = MagicMock()
        client.query.return_value.result.return_value = []
        keys = main.get_stale_candidate_keys(
            client, "GSO", "JiraTickets", "TAC", stale_days=90, max_candidates=500
        )
        self.assertEqual(keys, [])

    def test_query_uses_correct_parameters(self):
        client = MagicMock()
        client.query.return_value.result.return_value = []
        main.get_stale_candidate_keys(
            client, "GSO", "JiraTickets", "Global Service Delivery Team",
            stale_days=60, max_candidates=100,
        )
        job_config = client.query.call_args[1]["job_config"]
        params = {p.name: p.value for p in job_config.query_parameters}
        self.assertEqual(params["proj"], "Global Service Delivery Team")
        self.assertEqual(params["stale_days"], 60)
        self.assertEqual(params["max_candidates"], 100)


# ===========================================================================
# 7.  reconcile_project --- integration (all IO mocked)
# ===========================================================================
class TestReconcileProject(unittest.TestCase):

    def _bucket(self):
        """A TokenBucket with very high rate so tests don't wait."""
        return main.TokenBucket(1_000_000)

    def _bq_client(self, candidate_keys):
        """Return a BQ client mock pre-wired for candidates query + update."""
        candidate_rows = [MagicMock(Key=k) for k in candidate_keys]
        client = MagicMock()
        call_results = [
            candidate_rows,  # get_stale_candidate_keys
            None,            # apply_soft_deletes_bq (UPDATE)
        ]
        result_iter = iter(call_results)

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            mock_job.result.return_value = next(result_iter, [])
            return mock_job

        client.query.side_effect = _query_side_effect
        return client

    # ------ No candidates ------------------------------------------------------------------------------------------------------------------------------------------------------------

    def test_no_candidates_returns_no_candidates_status(self):
        client = MagicMock()
        client.query.return_value.result.return_value = []  # no stale candidates
        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "no_candidates")
        self.assertEqual(stats["candidates"], 0)
        self.assertEqual(stats["soft_deleted_bq"], 0)

    # ------ Normal flow: 3 candidates, 1 deleted, 1 exists, 1 error ------------------------------

    @patch("main.check_key_exists")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_normal_flow_correct_stats(self, mock_batch, mock_check):
        """End-to-end: 3 candidates --- 1 soft-deleted, 1 kept, 1 skipped."""
        jira_outcomes = {
            "PROJ-100": "deleted",
            "PROJ-200": "exists",
            "PROJ-300": "skip",
        }
        mock_check.side_effect = lambda key, auth, **kw: jira_outcomes[key]

        candidate_rows = [MagicMock(Key=k) for k in jira_outcomes]
        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "SyncTime" in sql:
                mock_job.result.return_value = candidate_rows
            else:
                mock_job.result.return_value = None  # UPDATE
            return mock_job

        client.query.side_effect = _query_side_effect

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )

        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["candidates"], 3)
        self.assertEqual(stats["checked"], 3)
        self.assertEqual(stats["confirmed_deleted"], 1)
        self.assertEqual(stats["skipped_on_error"], 1)
        self.assertEqual(stats["soft_deleted_bq"], 1)

    # ------ Dry-run: verified deletes are not written to BQ ---------------------------------------------------------

    @patch("main.check_key_exists", return_value="deleted")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_dry_run_no_bq_write(self, mock_batch, mock_check):
        candidate_rows = [MagicMock(Key="PROJ-1"), MagicMock(Key="PROJ-2")]
        client = MagicMock()
        client.query.return_value.result.return_value = candidate_rows

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=True,
        )

        # Confirmed deleted = 2, but BQ write = 0 (dry run)
        self.assertEqual(stats["confirmed_deleted"], 2)
        self.assertEqual(stats["soft_deleted_bq"], 0)

        # Verify no UPDATE was issued
        issued_sqls = [
            call_args[0][0]
            for call_args in client.query.call_args_list
            if call_args[0]
        ]
        self.assertFalse(
            any("IsDeleted = TRUE" in sql for sql in issued_sqls),
            "DRY RUN must not write IsDeleted=TRUE to BQ",
        )

    # ------ max_candidates cap respected ---------------------------------------------------------------------------------------------------------------------

    @patch("main.check_key_exists", return_value="exists")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_max_candidates_passed_to_bq(self, mock_batch, mock_check):
        client = MagicMock()
        client.query.return_value.result.return_value = []

        main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False, max_candidates=42,
        )

        # find the candidates query and check LIMIT param
        for call_args in client.query.call_args_list:
            if call_args[1] and "job_config" in call_args[1]:
                params = {p.name: p.value
                          for p in call_args[1]["job_config"].query_parameters}
                if "max_candidates" in params:
                    self.assertEqual(params["max_candidates"], 42)
                    break

    # ------ Circuit breaker trips on sustained timeouts/errors ------------------------------------------------------------------

    @patch("main.check_key_exists", return_value="skip")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_circuit_breaker_trips_on_high_skip_rate(self, mock_batch, mock_check):
        """When ≥80% of first 10 checks are skips, circuit breaker aborts project."""
        # 15 candidates (> CIRCUIT_BREAKER_MIN_CHECKS=10), all timeout → skip
        candidates = [MagicMock(Key=f"PROJ-{i}") for i in range(15)]
        client = MagicMock()
        client.query.return_value.result.return_value = candidates

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )

        self.assertEqual(stats["status"], "skipped_high_error_rate")
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertGreater(stats["skipped_on_error"], 0)

    # ------ Conservative on all-skip (no false deletions) ------------------------------------------------------------------

    @patch("main.check_key_exists", return_value="skip")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_all_skip_results_in_zero_deletes(self, mock_batch, mock_check):
        candidates = [MagicMock(Key=f"PROJ-{i}") for i in range(10)]
        client = MagicMock()
        client.query.return_value.result.return_value = candidates

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )

        self.assertEqual(stats["confirmed_deleted"], 0)
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertEqual(stats["skipped_on_error"], 10)


# ===========================================================================
# 8.  End-to-end data accuracy scenarios
# ===========================================================================
class TestDataAccuracyScenarios(unittest.TestCase):
    """
    Scenario-driven tests that verify the core data-accuracy guarantee:
    a ticket MUST NOT be soft-deleted unless the individual Jira API
    returns exactly HTTP 404.  The per-key check is the sole accuracy guard.
    """

    def _bucket(self):
        return main.TokenBucket(1_000_000)

    def _setup_bq_client(self, candidate_keys):
        candidates = [MagicMock(Key=k) for k in candidate_keys]
        client = MagicMock()

        def _query(sql_or_positional, *args, **kwargs):
            mock_job = MagicMock()
            sql = sql_or_positional if isinstance(sql_or_positional, str) else ""
            if "SyncTime" in sql:
                mock_job.result.return_value = candidates
            else:
                mock_job.result.return_value = None
            return mock_job

        client.query.side_effect = _query
        return client

    @patch("main.check_key_exists", return_value="exists")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_scenario_all_tickets_exist_zero_deletes(self, mock_batch, mock_check):
        """When every candidate is confirmed to still exist, nothing is deleted."""
        keys = [f"GSDT-{i}" for i in range(50)]
        client = self._setup_bq_client(keys)
        stats = main.reconcile_project(
            project="Global Service Delivery Team", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertEqual(stats["confirmed_deleted"], 0)

    @patch("main.check_key_exists")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_scenario_partial_deletion_only_confirmed(self, mock_batch, mock_check):
        """
        Of 5 stale candidates: 2 are 404, 2 are 200, 1 has a connection error.
        Only the 2 confirmed-404 tickets must be soft-deleted.
        """
        outcomes = {
            "GSDT-10": "deleted",
            "GSDT-20": "deleted",
            "GSDT-30": "exists",
            "GSDT-40": "exists",
            "GSDT-50": "skip",   # network error
        }
        mock_check.side_effect = lambda key, auth, **kw: outcomes[key]
        client = self._setup_bq_client(list(outcomes.keys()))

        stats = main.reconcile_project(
            project="Global Service Delivery Team", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["confirmed_deleted"], 2)
        self.assertEqual(stats["soft_deleted_bq"], 2)
        self.assertEqual(stats["skipped_on_error"], 1)

    @patch("main.check_key_exists", return_value="deleted")
    @patch("main.batch_check_keys_exist", side_effect=lambda keys, auth, bucket, **kw: (set(), set(keys)))
    def test_scenario_all_candidates_confirmed_deleted(self, mock_batch, mock_check):
        """When all candidates return 404, all are soft-deleted."""
        keys = [f"TAC-{i}" for i in range(10)]
        client = self._setup_bq_client(keys)

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["confirmed_deleted"], 10)
        self.assertEqual(stats["soft_deleted_bq"], 10)

    def test_scenario_no_stale_tickets_zero_api_calls(self):
        """If all tickets are recent, we make no Jira verification calls at all."""
        with patch("main.check_key_exists") as mock_chk:
            client = MagicMock()
            client.query.return_value.result.return_value = []  # no candidates

            stats = main.reconcile_project(
                project="TAC", auth=("u", "t"),
                client=client, bucket=self._bucket(), dry_run=False,
            )
            mock_chk.assert_not_called()
            self.assertEqual(stats["soft_deleted_bq"], 0)


# ===========================================================================
# 9.  SQL injection safety
# ===========================================================================
class TestSqlInjectionSafety(unittest.TestCase):

    def test_apply_soft_deletes_uses_parameterised_not_interpolated_keys(self):
        """
        The SQL issued to BQ must not contain raw key strings --- they must be
        passed via parameterised ARRAY to prevent injection.
        """
        client = MagicMock()
        client.query.return_value.result.return_value = None

        malicious_key = "PROJ-1'; UPDATE GSO.JiraTickets SET IsDeleted=FALSE--"
        main.apply_soft_deletes_bq(
            client, "GSO", "JiraTickets", [malicious_key], dry_run=False
        )

        sql_issued = client.query.call_args[0][0]
        self.assertNotIn(malicious_key, sql_issued,
                         "Malicious key must NOT appear in raw SQL")
        self.assertNotIn("UPDATE GSO", sql_issued)

        job_config = client.query.call_args[1]["job_config"]
        array_param = job_config.query_parameters[0]
        self.assertIn(malicious_key, array_param.value,
                      "Key value should be in the parameterised ARRAY")


# ===========================================================================
# 10. Request-level dry-run override
# ===========================================================================
class TestRequestDryRunOverride(unittest.TestCase):

    def test_resolve_request_dry_run_true(self):
        request = MagicMock()
        request.headers = {"X-DRY-RUN": "true"}
        self.assertTrue(main.resolve_request_dry_run(request))

    def test_resolve_request_dry_run_false(self):
        request = MagicMock()
        request.headers = {"X-DRY-RUN": "false"}
        self.assertFalse(main.resolve_request_dry_run(request))

    def test_main_passes_request_dry_run_override(self):
        request = MagicMock()
        request.headers = {"X-DRY-RUN": "true"}

        with patch("main.run_reconciliation") as mock_run:
            body, status = main.main(request)

        self.assertEqual(status, 200)
        self.assertEqual(body, "OK")
        mock_run.assert_called_once_with(dry_run_override=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)



