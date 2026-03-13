"""
pytest conftest for JiraDeleteReconciliation unit tests.

Stubs out Cloud Function / GCP imports before any test module is loaded,
so the test suite runs fully offline without any network activity or
credential access.  Stubbing happens at sys.modules level so that
`import main` never actually loads the heavy google-cloud C-extensions
(which on some Windows machines can take 40+ seconds due to AV scanning).
"""
import sys
import types
from collections import namedtuple
from unittest.mock import MagicMock


def _make_bigquery_stub():
    """
    Return a lightweight fake `bigquery` module with just enough surface
    area to let main.py be imported and unit-tested.

    Key contracts:
      --- bigquery.Client           --- MagicMock class (tests use MagicMock(spec=...))
      --- bigquery.QueryJobConfig   --- records query_parameters kwarg
      --- bigquery.ArrayQueryParameter  --- namedtuple('name','type_','value')
      --- bigquery.ScalarQueryParameter --- namedtuple('name','type_','value')
      --- bigquery.SchemaField      --- namedtuple('name','field_type','mode')
    """
    bq = types.ModuleType("google.cloud.bigquery")

    # Client is just a plain MagicMock class
    bq.Client = MagicMock

    # Parameter types implemented as namedtuples so tests can
    # inspect .name / .type_ / .value normally
    bq.ArrayQueryParameter = namedtuple(
        "ArrayQueryParameter", ["name", "type_", "value"]
    )
    bq.ScalarQueryParameter = namedtuple(
        "ScalarQueryParameter", ["name", "type_", "value"]
    )
    bq.SchemaField = namedtuple("SchemaField", ["name", "field_type", "mode"])

    # QueryJobConfig: store query_parameters so tests can inspect them
    class _QueryJobConfig:
        def __init__(self, query_parameters=None, **kwargs):
            self.query_parameters = query_parameters or []

    bq.QueryJobConfig = _QueryJobConfig
    return bq


def pytest_configure(config):
    """Insert all stubs before any test module is imported."""
    # ------ functions_framework ------------------------------------------------------------------------------------------------------------------------------------------------
    if "functions_framework" not in sys.modules:
        _ff = types.ModuleType("functions_framework")
        _ff.http = lambda fn: fn
        sys.modules["functions_framework"] = _ff

    # ------ google.cloud.bigquery ------------------------------------------------------------------------------------------------------------------------------------------
    bq_stub = _make_bigquery_stub()
    sys.modules.setdefault("google", types.ModuleType("google"))
    gc = types.ModuleType("google.cloud")
    sys.modules.setdefault("google.cloud", gc)
    sys.modules["google.cloud.bigquery"] = bq_stub

    # ------ google.cloud.secretmanager ---------------------------------------------------------------------------------------------------------------------------
    sm_stub = types.ModuleType("google.cloud.secretmanager")
    sm_stub.SecretManagerServiceClient = MagicMock
    sys.modules["google.cloud.secretmanager"] = sm_stub

