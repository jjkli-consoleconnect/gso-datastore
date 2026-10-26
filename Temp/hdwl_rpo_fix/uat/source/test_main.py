import base64
import csv
import importlib.util
import io
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
    "cloudevents",
    "cloudevents.http",
]:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

sys.modules["functions_framework"].cloud_event = lambda func: func
sys.modules["functions_framework"].http = lambda func: func

sys.modules["google"].__path__ = []
sys.modules["google.oauth2"].__path__ = []
sys.modules["google.cloud"].__path__ = []
sys.modules["googleapiclient"].__path__ = []
sys.modules["cloudevents"].__path__ = []

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
sys.modules["google.cloud.bigquery"].QueryJobConfig = lambda **kwargs: kwargs
sys.modules["google.cloud.bigquery"].ScalarQueryParameter = lambda *args: args
sys.modules["google.cloud.bigquery"].ArrayQueryParameter = lambda *args: args
sys.modules["google.cloud.pubsub_v1"].PublisherClient = object

sys.modules["googleapiclient.discovery"].build = lambda *args, **kwargs: None
sys.modules["googleapiclient.errors"].HttpError = type("HttpError", (Exception,), {})
sys.modules["cloudevents.http"].CloudEvent = object


MODULE_PATH = Path(__file__).with_name("main.py")
spec = importlib.util.spec_from_file_location("hdwl_main", MODULE_PATH)
hdwl_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hdwl_main)
sys.path.insert(0, str(MODULE_PATH.parents[3] / "shared"))
import parallel_gmail_validation

PROD_MODULE_PATH = MODULE_PATH.parents[3] / "pccw-internal-virtual-agent" / "CloudFunctions" / "bq_hdwl" / "main.py"
prod_spec = importlib.util.spec_from_file_location("prod_hdwl_main", PROD_MODULE_PATH)
prod_hdwl_main = importlib.util.module_from_spec(prod_spec)
prod_spec.loader.exec_module(prod_hdwl_main)


class HdwlRetryLoopTest(unittest.TestCase):
    def test_no_data_attachment_never_starts_a_bigquery_operation(self):
        for module in (hdwl_main, prod_hdwl_main):
            with self.subTest(module=module.__name__), patch.object(
                module, "get_message_attachment", return_value=b"No data"
            ), patch.object(module, "get_bq_client") as client:
                result = module.process_csv_attachment(
                    MagicMock(), "gmail1", "HelpDesk.csv", module.CSV_CONFIGURATIONS[0]
                )
            self.assertEqual(result, (True, 0, "upstream_no_data"))
            client.assert_not_called()

    def test_report_skip_reason_requires_all_attachments_explicitly_empty(self):
        cases = [
            ([(True, 0, "upstream_no_data"), (True, 0, "upstream_no_data")], "upstream_no_data", "INFO"),
            ([(True, 3, None), (True, 0, "upstream_no_data")], None, "INFO"),
            ([(True, 0, "unparseable_csv_payload"), (True, 0, "upstream_no_data")], None, "WARNING"),
            ([(True, 0, None), (True, 0, "upstream_no_data")], None, "INFO"),
        ]
        for module in (hdwl_main, prod_hdwl_main):
            for outcomes, expected_reason, expected_level in cases:
                with self.subTest(module=module.__name__, outcomes=outcomes):
                    event = types.SimpleNamespace(data={"message": {"data": base64.b64encode(
                        json.dumps({"messageId": "gmail1", "subject": "pubsub - HDWL"}).encode()
                    ).decode()}})
                    service = MagicMock()
                    service.users().messages().get().execute.return_value = {"payload": {"parts": [
                        {"filename": "HelpDesk.csv"}, {"filename": "WorkLog.csv"},
                    ]}}
                    with patch.object(module, "cleanup_stale_running"), patch.object(
                        module, "get_gmail_service", return_value=service
                    ), patch.object(module, "manage_gmail_labels"), patch.object(
                        module, "process_csv_attachment", side_effect=outcomes
                    ), patch.object(module, "log_pipeline_run") as audit:
                        module.process_bq_hdwl_email(event)
                    self.assertEqual(audit.call_args.args[1:3], ("SUCCESS", expected_level))
                    context = audit.call_args.args[8]
                    self.assertEqual(context.get("skipReason"), expected_reason)
                    self.assertEqual(audit.call_args.args[6], sum(item[1] for item in outcomes))

    def test_literal_no_data_is_not_a_generic_parse_failure(self):
        for module in (hdwl_main, prod_hdwl_main):
            for payload in (b"No data", b"No data\r\n", b"\xef\xbb\xbfNo data"):
                self.assertEqual(module.detect_known_non_data_payload(payload), "upstream_no_data")
            for payload in (b"No data,INC123", b"No data\nINC123", b"No\xff data", b""):
                self.assertNotEqual(module.detect_known_non_data_payload(payload), "upstream_no_data")

    def test_softdelete_control_email_is_not_a_csv_failure(self):
        message = {"payload": {"parts": [{"filename": "for soft delete 10-16.csv"}]}}
        self.assertTrue(
            hdwl_main.is_softdelete_control_message(
                {"subject": "pubsub - HD - softdelete"}, message
            )
        )
        self.assertTrue(
            hdwl_main.is_softdelete_control_message(
                {"subject": "pubsub - HDWL - softdelete"}, message
            )
        )
        self.assertTrue(
            hdwl_main.is_softdelete_control_message({}, message)
        )
        self.assertFalse(
            hdwl_main.is_softdelete_control_message(
                {"subject": "pubsub - HDWL"},
                {"payload": {"parts": [{"filename": "helpdesk.csv"}]}},
            )
        )

    def test_softdelete_control_email_is_acknowledged_without_csv_processing(self):
        event = types.SimpleNamespace(
            data={
                "message": {
                    "data": base64.b64encode(
                        json.dumps(
                            {
                                "messageId": "softdelete-message-123",
                                "subject": "pubsub - HD - softdelete",
                            }
                        ).encode("utf-8")
                    ).decode("utf-8")
                }
            }
        )
        fake_service = MagicMock()
        fake_service.users().messages().get().execute.return_value = {
            "payload": {
                "headers": [{"name": "Subject", "value": "pubsub - HD - softdelete"}],
                "parts": [
                    {"filename": "for soft delete 10-16-2026.csv", "mimeType": "text/csv"}
                ],
            }
        }

        with patch.object(hdwl_main, "cleanup_stale_running"), patch.object(
            hdwl_main, "get_gmail_service", return_value=fake_service
        ), patch.object(hdwl_main, "manage_gmail_labels") as manage_labels, patch.object(
            hdwl_main, "log_pipeline_run"
        ) as log_run:
            result = hdwl_main.process_bq_hdwl_email(event)

        self.assertIsNone(result)
        manage_labels.assert_called_once_with(
            fake_service,
            "softdelete-message-123",
            "pubsub",
            "ArchivedReports",
            extra_remove_label_name="HDWL_PROCESSING",
        )
        self.assertEqual(log_run.call_args.args[1:3], ("SUCCESS", "INFO"))
        self.assertEqual(
            log_run.call_args.args[8]["skipReason"],
            "softdelete_control_email",
        )

    def test_prod_push_adapter_accepts_only_explicit_zero_row_skip(self):
        self.assertTrue(
            parallel_gmail_validation.is_successful_pipeline_audit(
                "SUCCESS", 0, "upstream_no_data"
            )
        )
        self.assertFalse(
            parallel_gmail_validation.is_successful_pipeline_audit(
                "SUCCESS", 0, "unparseable_csv_payload"
            )
        )
        self.assertTrue(
            parallel_gmail_validation.is_successful_pipeline_audit(
                "SUCCESS", 0, "softdelete_control_email"
            )
        )
        self.assertFalse(
            parallel_gmail_validation.is_successful_pipeline_audit("SUCCESS", 0)
        )
        self.assertTrue(
            parallel_gmail_validation.is_successful_pipeline_audit("SUCCESS", 7)
        )
        self.assertFalse(
            parallel_gmail_validation.is_successful_pipeline_audit(
                "ERROR", 7, "softdelete_control_email"
            )
        )

    def test_legacy_hdwl_subject_is_also_recognized_as_softdelete(self):
        self.assertTrue(
            hdwl_main.is_softdelete_control_message(
                {"subject": "pubsub - HDWL - softdelete"},
                {"payload": {"parts": []}},
            )
        )

    def test_transient_bigquery_failures_are_retried_but_bad_requests_are_not(self):
        class ApiError(Exception):
            def __init__(self, status_code):
                self.code = status_code
                super().__init__(f"HTTP {status_code}")

        operation = MagicMock(side_effect=[ApiError(503), "complete"])
        with patch.object(hdwl_main.time, "sleep") as mock_sleep:
            result = hdwl_main.retry_bq_operation(operation, "test query")

        self.assertEqual(result, "complete")
        self.assertEqual(operation.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)
        self.assertTrue(hdwl_main.is_transient_bq_error(ApiError(503)))
        self.assertFalse(hdwl_main.is_transient_bq_error(ApiError(400)))

    def test_helpdesk_config_includes_status_reason_header(self):
        helpdesk_config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "HelpDeskAllNOC"
        )
        self.assertIn("Status_Reason", helpdesk_config["all_columns"])
        self.assertEqual(
            hdwl_main.standardize_field_name("Status_Reason", helpdesk_config["field_map"]),
            "Status_Reason",
        )

    def test_vip_is_optional_nullable_yes_no_and_source_presence_aware(self):
        for module in (hdwl_main, prod_hdwl_main):
            with self.subTest(module=module.__name__):
                config = next(
                    item for item in module.CSV_CONFIGURATIONS
                    if item["name"] == "HelpDeskAllNOC"
                )
                self.assertIn("VIP", config["all_columns"])
                self.assertIn("VIP", config["optional_columns"])
                self.assertNotIn("VIP", config["preserve_target_when_source_null"])
                self.assertEqual(module.normalize_vip_value(" Yes "), "Yes")
                self.assertEqual(module.normalize_vip_value("NO"), "No")
                self.assertIsNone(module.normalize_vip_value(""))
                self.assertIsNone(module.normalize_vip_value(" NULL "))
                self.assertIsNone(module.normalize_vip_value(None))
                with self.assertRaisesRegex(ValueError, "Invalid VIP value"):
                    module.normalize_vip_value("Unknown")

                staging_columns = ["Incident_Number", "VIP"]
                target_columns = ["Incident_Number", "VIP"]
                self.assertEqual(
                    module.get_merge_columns(
                        staging_columns, target_columns, ["Incident_Number"]
                    ),
                    ["Incident_Number"],
                )
                self.assertEqual(
                    module.get_merge_columns(
                        staging_columns, target_columns, ["Incident_Number", "VIP"]
                    ),
                    ["Incident_Number", "VIP"],
                )
                self.assertEqual(
                    module.get_missing_target_columns(
                        staging_columns + ["new_source_column"], target_columns
                    ),
                    ["new_source_column"],
                )

    def test_vip_header_is_optional_for_legacy_full_exports(self):
        for module in (hdwl_main, prod_hdwl_main):
            with self.subTest(module=module.__name__):
                config = next(item for item in module.CSV_CONFIGURATIONS
                              if item["name"] == "HelpDeskAllNOC")
                legacy_headers = [header for header in config["all_columns"] if header != "VIP"]
                self.assertEqual(module.locate_header_row([legacy_headers], config), 0)

    def test_legacy_helpdesk_header_without_status_reason_is_accepted(self):
        helpdesk_config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "HelpDeskAllNOC"
        )
        legacy_headers = [
            column for column in helpdesk_config["all_columns"]
            if column not in {"Status_Reason", "Remarks"}
        ]

        self.assertEqual(
            hdwl_main.locate_header_row([legacy_headers], helpdesk_config),
            0,
        )

    def test_helpdesk_legacy_and_enriched_headers_are_compatible(self):
        config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "HelpDeskAllNOC"
        )
        optional_fields = {
            "Status_Reason",
            "Remarks",
            "RPO_UMW_Reason",
            "Scheduled_Start_Date",
            "Scheduled_End_Date",
            "Planner",
        }
        older_headers = [
            field for field in config["all_columns"] if field not in optional_fields
        ]
        self.assertEqual(hdwl_main.locate_header_row([older_headers], config), 0)

        source_headers = [
            "RPO_UMW Reason",
            "Scheduled Start Date",
            "Scheduled End Date",
            "Planner",
        ]
        standardized = [
            hdwl_main.standardize_field_name(header, config["field_map"])
            for header in source_headers
        ]
        self.assertTrue(set(standardized).issubset(config["all_columns"]))
        self.assertTrue(set(standardized).issubset(config["optional_columns"]))
        self.assertTrue(
            set(standardized).issubset(config["preserve_target_when_source_null"])
        )
        self.assertEqual(
            hdwl_main.handle_empty_values(
                "2026-10-18 09:00:00", True, False
            ),
            "2026-10-18T09:00:00",
        )
        self.assertEqual(
            hdwl_main.handle_empty_values(
                "Reason: 50ms outage; see <ticket>\nFollow-up", False, False,
                preserve_text=True,
            ),
            "Reason: 50ms outage; see <ticket>\nFollow-up",
        )

    def test_helpdesk_remarks_preserves_csv_symbols_and_multiline_text(self):
        config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "HelpDeskAllNOC"
        )
        remarks_values = [
            '  "Quoted, text; with | pipes and \\ paths"\r\nSecond line\nThird\rLast\t  ',
            "Symbols: <>& ' $ % + = / ? @ #",
            "",
            "\u4e2d\u6587 \u00e9 \U0001f600 " + "Long remarks, with symbols; " * 6000,
        ]
        headers = config["all_columns"]
        output = io.StringIO(newline="")
        writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(headers)
        for index, remarks in enumerate(remarks_values):
            row = [""] * len(headers)
            row[headers.index("Incident_Number")] = f"INC{index}"
            row[headers.index("Remarks")] = remarks
            writer.writerow(row)

        parsed = hdwl_main.robust_parse_csv(output.getvalue().encode(), config)
        self.assertEqual(hdwl_main.locate_header_row(parsed, config), 0)
        self.assertIn("Remarks", config["optional_columns"])
        self.assertIn("Remarks", config["preserve_target_when_source_null"])
        self.assertIn("Remarks", config["raw_text_columns"])
        for parsed_row, expected in zip(parsed[1:], remarks_values):
            self.assertEqual(len(parsed_row), len(headers))
            actual = hdwl_main.handle_empty_values(
                parsed_row[headers.index("Remarks")], False, False,
                preserve_text=True,
            )
            self.assertEqual(json.loads(json.dumps(actual)), expected or None)

        previous_headers = [header for header in headers if header != "Remarks"]
        self.assertEqual(hdwl_main.locate_header_row([previous_headers], config), 0)

    def test_csv_parser_keeps_quoted_multiline_fields(self):
        csv_data = (
            'IncidentNumber,WorkLogID,ExtractedDescription\n'
            'INC1,WLG1,"first line\nsecond line with a ""quote"", and comma"\n'
        ).encode("utf-8")

        self.assertEqual(
            hdwl_main.robust_parse_csv(csv_data),
            [
                ["IncidentNumber", "WorkLogID", "ExtractedDescription"],
                ["INC1", "WLG1", 'first line\nsecond line with a "quote", and comma'],
            ],
        )

    def test_worklog_parser_does_not_select_semicolon_split_forwarded_text(self):
        config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "WorkLog"
        )
        headers = [
            "IncidentNumber",
            "WorkLogType",
            "WorkLogID",
            "WorkLogSubmitDate",
            "WorkLogSubmitter",
            "LastModifiedDate",
            "LastModifiedBy",
            "ExtractedDescription",
        ]
        rows = [
            headers,
            ["INC1", "Internal Work Log", "WLG1", "2026-10-06 01:00:00", "A", "2026-10-06 01:00:00", "A", "Forwarded; email; body; has; many; semicolon; delimiters; before; proper; header; detection; occurs"],
            ["INC2", "Internal Work Log", "WLG2", "2026-10-06 01:01:00", "B", "2026-10-06 01:01:00", "B", "Normal description"],
            ["INC3", "Internal Work Log", "WLG3", "2026-10-06 01:02:00", "C", "2026-10-06 01:02:00", "C", "Normal description"],
        ]
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerows(rows)

        parsed = hdwl_main.robust_parse_csv(
            output.getvalue().encode("utf-8"), config
        )
        header_index = hdwl_main.locate_header_row(parsed, config)

        self.assertEqual(header_index, 0)
        self.assertEqual(len(parsed[0]), len(config["all_columns"]))

    def test_worklog_rejoins_unquoted_commas_only_after_valid_record_prefix(self):
        config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "WorkLog"
        )
        headers = config["all_columns"]
        row = [
            "INC1",
            "Internal Work Log",
            "WLG0001",
            "2026-10-07 06:40:19",
            "Lisa Li",
            "2026-10-07 06:40:19",
            "Lisa Li",
            "Description contains",
            "unquoted commas",
            "that must stay together",
        ]

        csv_data = (",".join(headers) + "\n" + ",".join(row) + "\n").encode()
        parsed = hdwl_main.robust_parse_csv(csv_data, config)
        header_index = hdwl_main.locate_header_row(parsed, config)
        standardized_headers = [
            hdwl_main.standardize_field_name(header, config["field_map"])
            for header in parsed[header_index]
        ]
        parsed_row = parsed[header_index + 1]

        repaired = hdwl_main.repair_trailing_text_overflow(
            parsed_row, standardized_headers, config
        )

        self.assertIsNotNone(repaired)
        self.assertEqual(len(repaired), len(standardized_headers))
        self.assertEqual(
            repaired[-1],
            "Description contains,unquoted commas,that must stay together",
        )

        invalid_prefix = list(parsed_row)
        invalid_prefix[3] = "not a timestamp"
        self.assertIsNone(
            hdwl_main.repair_trailing_text_overflow(
                invalid_prefix, standardized_headers, config
            )
        )

    def test_worklog_forwarded_body_without_worklog_id_is_artifact(self):
        config = next(
            config for config in hdwl_main.CSV_CONFIGURATIONS
            if config["name"] == "WorkLog"
        )
        headers = config["all_columns"]
        forwarded_body_row = [
            " Dear Customer",
            "We have acknowledged your email/report and our team is ready to help.",
            "Regards",
            "Daniel Mangalindan",
        ]
        valid_worklog_row = [
            "INC0001",
            "Internal Work Log",
            "WLG0001",
            "2026-10-07 06:40:19",
            "Lisa Li",
            "2026-10-07 06:40:19",
            "Lisa Li",
            "WorkLog description",
        ]

        self.assertTrue(
            hdwl_main.is_worklog_forwarded_body_row(
                forwarded_body_row, headers, config
            )
        )
        self.assertFalse(
            hdwl_main.is_worklog_forwarded_body_row(
                valid_worklog_row, headers, config
            )
        )

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
