import base64
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# Stub cloud dependencies that are not installed in this local test environment.
for name in [
    "functions_framework",
    "google",
    "google.api_core",
    "google.api_core.exceptions",
    "google.oauth2",
    "google.oauth2.credentials",
    "google.cloud",
    "google.cloud.secretmanager",
    "google.cloud.bigquery",
    "google.cloud.pubsub_v1",
    "googleapiclient",
    "googleapiclient.discovery",
    "googleapiclient.errors",
]:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

sys.modules["functions_framework"].cloud_event = lambda func: func
sys.modules["functions_framework"].http = lambda func: func

sys.modules["google"].__path__ = []
sys.modules["google.oauth2"].__path__ = []
sys.modules["google.cloud"].__path__ = []
sys.modules["googleapiclient"].__path__ = []

sys.modules["google.api_core.exceptions"].NotFound = type("NotFound", (Exception,), {})
sys.modules["google.api_core.exceptions"].BadRequest = type("BadRequest", (Exception,), {})

class _Credentials:
    @staticmethod
    def from_authorized_user_info(data):
        return data

sys.modules["google.oauth2.credentials"].Credentials = _Credentials
sys.modules["google.cloud.secretmanager"].SecretManagerServiceClient = object
sys.modules["google.cloud.bigquery"].Client = object
sys.modules["google.cloud.bigquery"].SchemaField = object
sys.modules["google.cloud.bigquery"].SourceFormat = types.SimpleNamespace(NEWLINE_DELIMITED_JSON="json")
sys.modules["google.cloud.bigquery"].WriteDisposition = types.SimpleNamespace(WRITE_TRUNCATE="truncate")
sys.modules["google.cloud.bigquery"].LoadJobConfig = object
sys.modules["google.cloud.bigquery"].QueryJobConfig = object
sys.modules["google.cloud.pubsub_v1"].PublisherClient = object

sys.modules["googleapiclient.discovery"].build = lambda *args, **kwargs: None
sys.modules["googleapiclient.errors"].HttpError = type("HttpError", (Exception,), {})


MODULE_PATH = Path(__file__).with_name("main.py")
spec = importlib.util.spec_from_file_location("hdwl_main", MODULE_PATH)
hdwl_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hdwl_main)


class HdwlRetryLoopTest(unittest.TestCase):
    def test_failed_hdwl_message_is_archived_instead_of_retried(self):
        event = types.SimpleNamespace(
            data={
                "message": {
                    "data": base64.b64encode(
                        json.dumps({"messageId": "bad-message-123"}).encode("utf-8")
                    ).decode("utf-8")
                }
            }
        )

        fake_service = MagicMock()
        fake_service.users().messages().get().execute.return_value = {
            "payload": {
                "parts": [
                    {"filename": "worklog 09-23-2026 5-36-11.csv", "mimeType": "text/csv"}
                ]
            }
        }

        with patch.object(hdwl_main, "cleanup_stale_running"), patch.object(
            hdwl_main, "get_gmail_service", return_value=fake_service
        ), patch.object(
            hdwl_main,
            "process_csv_attachment",
            return_value=(False, 0, None),
        ), patch.object(
            hdwl_main,
            "manage_gmail_labels",
        ) as mock_manage_labels, patch.object(
            hdwl_main,
            "log_pipeline_run",
        ):
            result = hdwl_main.process_bq_hdwl_email(event)

        self.assertIsNone(result)
        mock_manage_labels.assert_called_once_with(
            fake_service,
            "bad-message-123",
            "pubsub",
            "ArchivedReports",
            extra_remove_label_name="HDWL_PROCESSING",
        )


if __name__ == "__main__":
    unittest.main()
