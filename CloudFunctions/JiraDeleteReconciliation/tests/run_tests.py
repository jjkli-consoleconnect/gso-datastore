"""
Standalone test runner --- runs all reconciliation unit tests without pytest.
Usage: python tests/run_tests.py
"""
import sys
import os
import types
import unittest
from collections import namedtuple
from unittest.mock import MagicMock

# ------ Setup: ensure the function directory is importable ------------------------------------------------------------------
FUNC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if FUNC_DIR not in sys.path:
    sys.path.insert(0, FUNC_DIR)

# ------ Stub ALL GCP/framework modules so main.py can be imported offline ------------------------
# functions_framework
if "functions_framework" not in sys.modules:
    _ff = types.ModuleType("functions_framework")
    _ff.http = lambda fn: fn
    sys.modules["functions_framework"] = _ff

# google.cloud.bigquery --- lightweight stub with namedtuple parameter types
def _make_bq_stub():
    bq = types.ModuleType("google.cloud.bigquery")
    bq.Client = MagicMock
    bq.ArrayQueryParameter = namedtuple("ArrayQueryParameter", ["name", "type_", "value"])
    bq.ScalarQueryParameter = namedtuple("ScalarQueryParameter", ["name", "type_", "value"])
    bq.SchemaField = namedtuple("SchemaField", ["name", "field_type", "mode"])
    class _QJC:
        def __init__(self, query_parameters=None, **kw):
            self.query_parameters = query_parameters or []
    bq.QueryJobConfig = _QJC
    return bq

sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
sys.modules["google.cloud.bigquery"] = _make_bq_stub()
_sm = types.ModuleType("google.cloud.secretmanager")
_sm.SecretManagerServiceClient = MagicMock
sys.modules["google.cloud.secretmanager"] = _sm

# ------ Now import the test cases ------------------------------------------------------------------------------------------------------------------------------------------------
from test_reconciliation import (  # noqa: E402
    TestBuildProjJql,
    TestPassesCountGate,
    TestTokenBucket,
    TestGetJiraApproximateCount,
    TestCheckKeyExists,
    TestApplySoftDeletesBq,
    TestGetBqActiveCount,
    TestGetStaleCandidateKeys,
    TestReconcileProject,
    TestDataAccuracyScenarios,
    TestSqlInjectionSafety,
    TestRequestDryRunOverride,
)


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestBuildProjJql,
        TestPassesCountGate,
        TestTokenBucket,
        TestGetJiraApproximateCount,
        TestCheckKeyExists,
        TestApplySoftDeletesBq,
        TestGetBqActiveCount,
        TestGetStaleCandidateKeys,
        TestReconcileProject,
        TestDataAccuracyScenarios,
        TestSqlInjectionSafety,
        TestRequestDryRunOverride,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

