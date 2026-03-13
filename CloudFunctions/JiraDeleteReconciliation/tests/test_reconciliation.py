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
# 1.  Pure helper: _build_proj_jql
# ===========================================================================
class TestBuildProjJql(unittest.TestCase):

    def test_simple_name_no_quotes(self):
        result = main._build_proj_jql("TAC")
        self.assertEqual(result, "project = TAC")

    def test_name_with_space_is_quoted(self):
        result = main._build_proj_jql("Global Service Delivery Team")
        self.assertIn('"', result)
        self.assertIn("Global Service Delivery Team", result)

    def test_name_with_ampersand_is_quoted(self):
        result = main._build_proj_jql("GS&O Data Analytics")
        self.assertIn('"', result)
        self.assertIn("GS&O Data Analytics", result)

    def test_quoted_name_has_correct_jql_structure(self):
        result = main._build_proj_jql("Console Connect Provisioning")
        self.assertEqual(result, 'project = "Console Connect Provisioning"')

    def test_name_with_embedded_quote_is_escaped(self):
        # Should not raise; backslash-escape any internal double-quotes
        result = main._build_proj_jql('Foo "Bar"')
        self.assertIn('\\"', result)


# ===========================================================================
# 2.  Pure helper: passes_count_gate
# ===========================================================================
class TestPassesCountGate(unittest.TestCase):

    def test_passes_when_ratio_above_threshold(self):
        passes, ratio = main.passes_count_gate(1000, 1000, 0.70)
        self.assertTrue(passes)
        self.assertAlmostEqual(ratio, 1.0)

    def test_passes_at_exact_threshold(self):
        passes, ratio = main.passes_count_gate(700, 1000, 0.70)
        self.assertTrue(passes)
        self.assertAlmostEqual(ratio, 0.70)

    def test_fails_below_threshold(self):
        passes, ratio = main.passes_count_gate(100, 229_064, 0.70)
        self.assertFalse(passes)
        self.assertLess(ratio, 0.001)

    def test_passes_when_bq_count_is_zero(self):
        # Nothing to protect --- always passes
        passes, ratio = main.passes_count_gate(0, 0, 0.70)
        self.assertTrue(passes)
        self.assertAlmostEqual(ratio, 1.0)

    def test_fails_when_jira_count_is_zero_bq_nonempty(self):
        passes, _ = main.passes_count_gate(0, 500, 0.70)
        self.assertFalse(passes)

    def test_custom_threshold(self):
        passes_hi, _ = main.passes_count_gate(800, 1000, 0.90)
        self.assertFalse(passes_hi)
        passes_lo, _ = main.passes_count_gate(800, 1000, 0.75)
        self.assertTrue(passes_lo)


# ===========================================================================
# 3.  TokenBucket --- rate limiting
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
# 4.  get_jira_approximate_count
# ===========================================================================
class TestGetJiraApproximateCount(unittest.TestCase):

    def _mock_response(self, status_code, json_body=None, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_body or {}
        resp.headers = headers or {}
        # raise_for_status: raise for 4xx/5xx, pass otherwise
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        else:
            resp.raise_for_status.return_value = None
        return resp

    @patch("main.requests.post")
    def test_returns_total_on_success(self, mock_get):
        mock_get.return_value = self._mock_response(200, {"count": 12345})
        count = main.get_jira_approximate_count("project = TAC", ("user", "tok"))
        self.assertEqual(count, 12345)
        self.assertEqual(mock_get.call_args.args[0], main.JIRA_APPROX_COUNT_URL)
        self.assertEqual(mock_get.call_args.kwargs["json"]["jql"], "project = TAC")

    @patch("main.requests.post")
    def test_returns_zero_total(self, mock_get):
        mock_get.return_value = self._mock_response(200, {"count": 0})
        count = main.get_jira_approximate_count("project = TAC", ("user", "tok"))
        self.assertEqual(count, 0)

    @patch("main.requests.post")
    @patch("main.time.sleep", return_value=None)
    def test_returns_none_after_all_failures(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("network error")
        count = main.get_jira_approximate_count(
            "project = TAC", ("user", "tok"), max_retries=3
        )
        self.assertIsNone(count)
        self.assertEqual(mock_get.call_count, 3)

    @patch("main.requests.post")
    @patch("main.time.sleep", return_value=None)
    def test_retries_on_429_then_succeeds(self, mock_sleep, mock_get):
        rate_limited = self._mock_response(429, headers={"Retry-After": "1"})
        rate_limited.raise_for_status.return_value = None  # 429 not raised here
        success = self._mock_response(200, {"count": 500})
        mock_get.side_effect = [rate_limited, success]

        count = main.get_jira_approximate_count(
            "project = TAC", ("user", "tok"), max_retries=5
        )
        self.assertEqual(count, 500)
        self.assertEqual(mock_get.call_count, 2)


# ===========================================================================
# 5.  check_key_exists
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
# 6.  apply_soft_deletes_bq
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
# 7.  get_bq_active_count
# ===========================================================================
class TestGetBqActiveCount(unittest.TestCase):

    def _make_bq_client(self, count_value):
        row = MagicMock()
        row.cnt = count_value
        client = MagicMock()
        client.query.return_value.result.return_value = [row]
        return client

    def test_returns_count(self):
        client = self._make_bq_client(12_345)
        result = main.get_bq_active_count(client, "GSO", "JiraTickets", "TAC")
        self.assertEqual(result, 12_345)

    def test_parameterised_query_used(self):
        client = self._make_bq_client(0)
        main.get_bq_active_count(client, "GSO", "JiraTickets", "TAC")
        job_config = client.query.call_args[1]["job_config"]
        params = {p.name: p.value for p in job_config.query_parameters}
        self.assertEqual(params["proj"], "TAC")

    def test_zero_rows_returns_zero(self):
        client = MagicMock()
        client.query.return_value.result.return_value = []
        result = main.get_bq_active_count(client, "GSO", "JiraTickets", "TAC")
        self.assertEqual(result, 0)


# ===========================================================================
# 7b.  get_bq_min_created
# ===========================================================================
class TestGetBqMinCreated(unittest.TestCase):

    def _make_client(self, min_created_value):
        row = MagicMock()
        row.min_created = min_created_value
        client = MagicMock()
        client.query.return_value.result.return_value = [row]
        return client

    def test_returns_date_string_when_created_found(self):
        from datetime import datetime
        dt = datetime(2021, 9, 24, 12, 50, 26)
        client = self._make_client(dt)
        result = main.get_bq_min_created(client, "GSO", "JiraTickets", "Mobility SMS - CE")
        self.assertEqual(result, "2021-09-24")

    def test_returns_none_when_no_rows(self):
        client = MagicMock()
        client.query.return_value.result.return_value = []
        result = main.get_bq_min_created(client, "GSO", "JiraTickets", "TAC")
        self.assertIsNone(result)

    def test_returns_none_when_min_created_is_null(self):
        row = MagicMock()
        row.min_created = None
        client = MagicMock()
        client.query.return_value.result.return_value = [row]
        result = main.get_bq_min_created(client, "GSO", "JiraTickets", "TAC")
        self.assertIsNone(result)

    def test_parameterised_query_used(self):
        from datetime import datetime
        client = self._make_client(datetime(2022, 1, 1))
        main.get_bq_min_created(client, "GSO", "JiraTickets", "Mobility SMS - CE")
        job_config = client.query.call_args[1]["job_config"]
        params = {p.name: p.value for p in job_config.query_parameters}
        self.assertEqual(params["proj"], "Mobility SMS - CE")

    def test_sql_selects_min_created(self):
        from datetime import datetime
        client = self._make_client(datetime(2022, 1, 1))
        main.get_bq_min_created(client, "GSO", "JiraTickets", "TAC")
        sql = client.query.call_args[0][0]
        self.assertIn("MIN(Created)", sql)


# ===========================================================================
# 8.  get_stale_candidate_keys
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
# 9.  reconcile_project --- integration (all IO mocked)
# ===========================================================================
class TestReconcileProject(unittest.TestCase):

    def _bucket(self):
        """A TokenBucket with very high rate so tests don't wait."""
        return main.TokenBucket(1_000_000)

    def _bq_client(self, active_count, candidate_keys):
        """Return a BQ client mock pre-wired for count + candidates."""
        count_row = MagicMock()
        count_row.cnt = active_count

        candidate_rows = [MagicMock(Key=k) for k in candidate_keys]

        client = MagicMock()

        # First call --- count, subsequent calls --- candidates / update
        call_results = [
            [count_row],        # get_bq_active_count
            candidate_rows,     # get_stale_candidate_keys
            None,               # apply_soft_deletes_bq (UPDATE)
        ]
        result_iter = iter(call_results)

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            mock_job.result.return_value = next(result_iter, [])
            return mock_job

        client.query.side_effect = _query_side_effect
        return client

    # ------ Count gate failure ------------------------------------------------------------------------------------------------------------------------------------------------------

    @patch("main.get_jira_approximate_count", return_value=50)
    def test_count_gate_fail_skips_project(self, mock_count):
        """When Jira returns far fewer keys than BQ, the project is skipped."""
        # BQ has 10,000 active rows; Jira returns 50 --- ratio = 0.5% (< 70%)
        count_row = MagicMock(); count_row.cnt = 10_000
        client = MagicMock()
        client.query.return_value.result.return_value = [count_row]

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "skipped_count_gate")
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertEqual(stats["candidates"], 0)

    # ------ Jira count API failure ------------------------------------------------------------------------------------------------------------------------------------

    @patch("main.get_jira_approximate_count", return_value=None)
    def test_count_api_failure_skips_project(self, mock_count):
        client = MagicMock()
        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "skipped_error")
        self.assertEqual(stats["soft_deleted_bq"], 0)

    # ------ No candidates ------------------------------------------------------------------------------------------------------------------------------------------------------------

    @patch("main.get_jira_approximate_count", return_value=1_000)
    def test_no_candidates_returns_no_candidates_status(self, mock_count):
        count_row = MagicMock(); count_row.cnt = 1_000  # ratio = 1.0 (passes gate)
        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            else:
                mock_job.result.return_value = []  # no stale candidates
            return mock_job

        client.query.side_effect = _query_side_effect

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "no_candidates")
        self.assertEqual(stats["candidates"], 0)
        self.assertEqual(stats["soft_deleted_bq"], 0)

    # ------ Normal flow: 3 candidates, 1 deleted, 1 exists, 1 error ------------------------------

    @patch("main.get_jira_approximate_count", return_value=1_000)
    @patch("main.check_key_exists")
    def test_normal_flow_correct_stats(self, mock_check, mock_count):
        """End-to-end: 3 candidates --- 1 soft-deleted, 1 kept, 1 skipped."""
        jira_outcomes = {
            "PROJ-100": "deleted",
            "PROJ-200": "exists",
            "PROJ-300": "skip",
        }
        mock_check.side_effect = lambda key, auth, **kw: jira_outcomes[key]

        count_row = MagicMock(); count_row.cnt = 1_000
        candidate_rows = [MagicMock(Key=k) for k in jira_outcomes]

        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            elif "MIN(Created)" in sql:
                mock_job.result.return_value = []   # no min date
            elif "SyncTime" in sql:
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

    @patch("main.get_jira_approximate_count", return_value=1_000)
    @patch("main.check_key_exists", return_value="deleted")
    def test_dry_run_no_bq_write(self, mock_check, mock_count):
        count_row = MagicMock(); count_row.cnt = 1_000
        candidate_rows = [MagicMock(Key="PROJ-1"), MagicMock(Key="PROJ-2")]

        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            elif "MIN(Created)" in sql:
                mock_job.result.return_value = []   # no min date
            else:
                mock_job.result.return_value = candidate_rows
            return mock_job

        client.query.side_effect = _query_side_effect

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

    @patch("main.get_jira_approximate_count", return_value=1_000)
    @patch("main.check_key_exists", return_value="exists")
    def test_max_candidates_passed_to_bq(self, mock_check, mock_count):
        count_row = MagicMock(); count_row.cnt = 1_000
        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            else:
                mock_job.result.return_value = []
            return mock_job

        client.query.side_effect = _query_side_effect

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

    # ------ Date-aligned count gate JQL -----------------------------------------------------------------------

    @patch("main.get_bq_min_created", return_value="2021-09-24")
    @patch("main.get_jira_approximate_count")
    def test_count_gate_jql_scoped_when_min_created_known(self, mock_count, mock_min):
        """Count-gate JQL must include created >= filter when BQ min date is available."""
        mock_count.return_value = 5_000
        count_row = MagicMock(); count_row.cnt = 5_000
        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            else:
                mock_job.result.return_value = []  # no candidates
            return mock_job

        client.query.side_effect = _query_side_effect

        main.reconcile_project(
            project="Mobility SMS - CE", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=True,
        )

        jql_used = mock_count.call_args[0][0]
        self.assertIn('created >= "2021-09-24"', jql_used)
        self.assertIn("Mobility SMS - CE", jql_used)

    # ------ Conservative on all-skip (no false deletions) ------------------------------------------------------------------

    @patch("main.get_jira_approximate_count", return_value=1_000)
    @patch("main.check_key_exists", return_value="skip")
    def test_all_skip_results_in_zero_deletes(self, mock_check, mock_count):
        count_row = MagicMock(); count_row.cnt = 1_000
        candidates = [MagicMock(Key=f"PROJ-{i}") for i in range(10)]

        client = MagicMock()

        def _query_side_effect(*args, **kwargs):
            mock_job = MagicMock()
            sql = args[0] if args else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            elif "MIN(Created)" in sql:
                mock_job.result.return_value = []   # no min date
            else:
                mock_job.result.return_value = candidates
            return mock_job

        client.query.side_effect = _query_side_effect

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"), client=client,
            bucket=self._bucket(), dry_run=False,
        )

        self.assertEqual(stats["confirmed_deleted"], 0)
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertEqual(stats["skipped_on_error"], 10)


# ===========================================================================
# 10. End-to-end data accuracy scenarios
# ===========================================================================
class TestDataAccuracyScenarios(unittest.TestCase):
    """
    Scenario-driven tests that verify the core data-accuracy guarantee:
    a ticket MUST NOT be soft-deleted unless:
      (a) the count gate passes, AND
      (b) the individual Jira API returns exactly HTTP 404.
    """

    def _bucket(self):
        return main.TokenBucket(1_000_000)

    def _setup_bq_client(self, bq_count, candidate_keys):
        count_row = MagicMock(); count_row.cnt = bq_count
        candidates = [MagicMock(Key=k) for k in candidate_keys]
        client = MagicMock()

        def _query(sql_or_positional, *args, **kwargs):
            mock_job = MagicMock()
            sql = sql_or_positional if isinstance(sql_or_positional, str) else ""
            if "COUNT(*)" in sql:
                mock_job.result.return_value = [count_row]
            elif "MIN(Created)" in sql:
                mock_job.result.return_value = []   # no min date
            elif "SyncTime" in sql:
                mock_job.result.return_value = candidates
            else:
                mock_job.result.return_value = None
            return mock_job

        client.query.side_effect = _query
        return client

    @patch("main.get_jira_approximate_count", return_value=100)
    def test_scenario_truncated_response_blocked_by_count_gate(self, mock_count):
        """
        Simulates the original bug: Jira returns 100 keys for a project that
        has 229,064 BQ rows.  Count gate must block all deletes.
        """
        client = self._setup_bq_client(229_064, [f"GSDT-{i}" for i in range(500)])
        stats = main.reconcile_project(
            project="Global Service Delivery Team", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "skipped_count_gate",
                         "Truncated Jira result must be blocked by count gate")
        self.assertEqual(stats["soft_deleted_bq"], 0)

    @patch("main.get_jira_approximate_count", return_value=229_064)
    @patch("main.check_key_exists", return_value="exists")
    def test_scenario_all_tickets_exist_zero_deletes(self, mock_check, mock_count):
        """When every candidate is confirmed to still exist, nothing is deleted."""
        keys = [f"GSDT-{i}" for i in range(50)]
        client = self._setup_bq_client(229_064, keys)
        stats = main.reconcile_project(
            project="Global Service Delivery Team", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["soft_deleted_bq"], 0)
        self.assertEqual(stats["confirmed_deleted"], 0)

    @patch("main.get_jira_approximate_count", return_value=229_000)
    @patch("main.check_key_exists")
    def test_scenario_partial_deletion_only_confirmed(self, mock_check, mock_count):
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
        client = self._setup_bq_client(229_000, list(outcomes.keys()))

        stats = main.reconcile_project(
            project="Global Service Delivery Team", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["confirmed_deleted"], 2)
        self.assertEqual(stats["soft_deleted_bq"], 2)
        self.assertEqual(stats["skipped_on_error"], 1)

    @patch("main.get_jira_approximate_count", return_value=500)
    @patch("main.check_key_exists", return_value="deleted")
    def test_scenario_count_gate_passes_then_deletes_applied(self, mock_check, mock_count):
        """When Jira count is close to BQ count and all candidates are 404."""
        keys = [f"TAC-{i}" for i in range(10)]
        client = self._setup_bq_client(500, keys)

        stats = main.reconcile_project(
            project="TAC", auth=("u", "t"),
            client=client, bucket=self._bucket(), dry_run=False,
        )
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["confirmed_deleted"], 10)
        self.assertEqual(stats["soft_deleted_bq"], 10)

    def test_scenario_no_stale_tickets_zero_api_calls(self):
        """If all tickets are recent, we make no Jira verification calls at all."""
        with patch("main.get_jira_approximate_count", return_value=300) as mock_cnt, \
             patch("main.check_key_exists") as mock_chk:
            count_row = MagicMock(); count_row.cnt = 300
            client = MagicMock()

            def _query(sql, *args, **kwargs):
                mock_job = MagicMock()
                if "COUNT(*)" in sql:
                    mock_job.result.return_value = [count_row]
                else:
                    mock_job.result.return_value = []  # no candidates
                return mock_job

            client.query.side_effect = _query

            stats = main.reconcile_project(
                project="TAC", auth=("u", "t"),
                client=client, bucket=self._bucket(), dry_run=False,
            )
            mock_chk.assert_not_called()
            self.assertEqual(stats["soft_deleted_bq"], 0)


# ===========================================================================
# 11. SQL injection safety
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
# 12. Request-level dry-run override
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



