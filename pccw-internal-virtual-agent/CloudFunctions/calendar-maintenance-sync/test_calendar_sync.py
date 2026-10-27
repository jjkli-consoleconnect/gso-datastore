import json
import io
import re
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import PermissionDenied
from google.auth.exceptions import RefreshError
from google.cloud.bigquery import Row
from googleapiclient.errors import HttpError
from httplib2 import Response

import calendar_auth
import authorize
import deploy
import main


def http_error(status):
    return HttpError(Response({"status": str(status)}), b'{"error":{"message":"test error"}}')


def maintenance_row(**overrides):
    values = {
        "Incident_Number": "INC/123 A",
        "Customer_Name": "Test customer",
        "Planner": "Planner",
        "RPO_UMW_Reason": "Maintenance",
        "Scheduled_Start_Date": datetime(2026, 10, 28, 1, tzinfo=timezone.utc),
        "Scheduled_End_Date": datetime(2026, 10, 28, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return Row(tuple(values.values()), {name: index for index, name in enumerate(values)})


class UserOAuthTests(unittest.TestCase):
    def setUp(self):
        self.info = {
            "type": "authorized_user",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh",
        }
        credentials_patch = patch.object(calendar_auth.Credentials, "from_authorized_user_info")
        self.factory = credentials_patch.start()
        self.addCleanup(credentials_patch.stop)
        self.credentials = self.factory.return_value
        self.credentials.granted_scopes = calendar_auth.OAUTH_SCOPES
        session_patch = patch.object(calendar_auth, "AuthorizedSession")
        self.session = session_patch.start()
        self.addCleanup(session_patch.stop)
        self.response = self.session.return_value.__enter__.return_value.get.return_value
        self.response.json.return_value = {
            "email": calendar_auth.EXPECTED_USER_EMAIL,
            "verified_email": True,
        }

    def test_refreshes_and_verifies_expected_user(self):
        self.assertIs(calendar_auth.verified_user_credentials(self.info), self.credentials)
        self.credentials.refresh.assert_called_once()
        self.factory.assert_called_once_with(self.info)
        self.session.return_value.__enter__.return_value.get.assert_called_once_with(
            "https://www.googleapis.com/oauth2/v2/userinfo", timeout=30
        )

    def test_service_account_and_impersonated_types_rejected(self):
        for credential_type in ("service_account", "impersonated_service_account", None):
            with self.subTest(credential_type=credential_type):
                with self.assertRaises(calendar_auth.CalendarAuthError):
                    calendar_auth.verified_user_credentials({**self.info, "type": credential_type})
        self.factory.assert_not_called()

    def test_incomplete_refresh_credentials_rejected(self):
        for key in ("refresh_token", "client_id", "client_secret"):
            with self.subTest(key=key):
                with self.assertRaises(calendar_auth.CalendarAuthError):
                    calendar_auth.verified_user_credentials({**self.info, key: ""})
        self.factory.assert_not_called()

    def test_refresh_failure_does_not_leak_details_or_fall_back(self):
        self.credentials.refresh.side_effect = RefreshError("sensitive-token-must-not-be-logged")
        with self.assertRaises(calendar_auth.CalendarAuthError) as caught:
            calendar_auth.verified_user_credentials(self.info)
        self.assertNotIn("sensitive-token", str(caught.exception))
        self.session.assert_not_called()

    def test_missing_or_unproven_calendar_consent_rejected(self):
        for scopes in (None, (), (calendar_auth.EMAIL_SCOPE,), (calendar_auth.CALENDAR_SCOPE,)):
            with self.subTest(scopes=scopes):
                self.credentials.granted_scopes = scopes
                with self.assertRaisesRegex(calendar_auth.CalendarAuthError, "lacks Calendar or email"):
                    calendar_auth.verified_user_credentials(self.info)
        self.session.assert_not_called()

    def test_wrong_unverified_or_malformed_identity_rejected(self):
        for identity in (
            {"email": "someone@consoleconnect.com", "verified_email": True},
            {"email": calendar_auth.EXPECTED_USER_EMAIL, "verified_email": False},
            {"email": calendar_auth.EXPECTED_USER_EMAIL},
            [],
        ):
            with self.subTest(identity=identity):
                self.response.json.return_value = identity
                with self.assertRaises(calendar_auth.CalendarAuthError):
                    calendar_auth.verified_user_credentials(self.info)

    def test_userinfo_failure_is_explicit(self):
        from requests.exceptions import HTTPError

        self.response.raise_for_status.side_effect = HTTPError("denied")
        with self.assertRaisesRegex(calendar_auth.CalendarAuthError, "Unable to verify"):
            calendar_auth.verified_user_credentials(self.info)


class AccessAndSecretTests(unittest.TestCase):
    def test_writable_roles_accepted_and_read_only_roles_rejected(self):
        service = MagicMock()
        for role in ("owner", "writer", "writerWithoutPrivateAccess"):
            with self.subTest(role=role):
                service.events.return_value.list.return_value.execute.return_value = {"accessRole": role}
                self.assertEqual(calendar_auth.require_calendar_write_access(service, "target"), role)
        for role in ("reader", "freeBusyReader", None):
            with self.subTest(role=role):
                service.events.return_value.list.return_value.execute.return_value = {"accessRole": role}
                with self.assertRaisesRegex(calendar_auth.CalendarAuthError, "needs writer access"):
                    calendar_auth.require_calendar_write_access(service, "target")
        service.events.return_value.list.assert_called_with(
            calendarId="target", maxResults=1, fields="accessRole"
        )
        service.calendarList.assert_not_called()

    def test_access_http_errors_fail_explicitly(self):
        service = MagicMock()
        for status in (401, 403, 404, 500):
            with self.subTest(status=status):
                service.events.return_value.list.return_value.execute.side_effect = http_error(status)
                with self.assertRaisesRegex(calendar_auth.CalendarAuthError, f"HTTP {status}"):
                    calendar_auth.require_calendar_write_access(service, "target")

    @patch.object(main, "build")
    @patch.object(main.secretmanager, "SecretManagerServiceClient")
    def test_secret_failure_cannot_fall_back(self, secret_factory, build):
        secret_factory.return_value.access_secret_version.side_effect = PermissionDenied("test denied")
        with self.assertRaises(PermissionDenied):
            main.get_calendar_service()
        build.assert_not_called()

    @patch.object(main, "build")
    @patch.object(main.secretmanager, "SecretManagerServiceClient")
    def test_invalid_secret_cannot_fall_back(self, secret_factory, build):
        for data in (b"not-json", b"[]"):
            secret_factory.return_value.access_secret_version.return_value = SimpleNamespace(
                payload=SimpleNamespace(data=data)
            )
            with self.subTest(data=data):
                with self.assertRaises(calendar_auth.CalendarAuthError):
                    main.get_calendar_service()
        build.assert_not_called()

    @patch.object(main, "require_calendar_write_access")
    @patch.object(main, "build")
    @patch.object(main, "verified_user_credentials")
    @patch.object(main.secretmanager, "SecretManagerServiceClient")
    def test_only_verified_user_credentials_reach_calendar(self, secret_factory, verify, build, access):
        info = {"type": "authorized_user"}
        secret_factory.return_value.access_secret_version.return_value = SimpleNamespace(
            payload=SimpleNamespace(data=json.dumps(info).encode())
        )
        self.assertIs(main.get_calendar_service(), build.return_value)
        verify.assert_called_once_with(info)
        build.assert_called_once_with(
            "calendar", "v3", credentials=verify.return_value, cache_discovery=False
        )
        access.assert_called_once_with(build.return_value, main.CALENDAR_ID)


class EventSyncTests(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.events = self.service.events.return_value
        self.row = maintenance_row()

    def test_id_is_valid_stable_and_distinguishes_keys(self):
        event_id = main.event_id_for_row(self.row)
        self.assertIsNotNone(re.fullmatch(r"[0-9a-v]{5,1024}", event_id))
        self.assertEqual(event_id, main.event_id_for_row(self.row))
        same_instant = self.row.Scheduled_Start_Date.astimezone(timezone(timedelta(hours=8)))
        self.assertEqual(event_id, main.event_id_for_row(maintenance_row(Scheduled_Start_Date=same_instant)))
        self.assertEqual(
            event_id,
            main.event_id_for_row(maintenance_row(Scheduled_Start_Date=self.row.Scheduled_Start_Date.replace(tzinfo=None))),
        )
        self.assertNotEqual(event_id, main.event_id_for_row(maintenance_row(Incident_Number="INC456")))
        self.assertNotEqual(
            event_id,
            main.event_id_for_row(maintenance_row(Scheduled_Start_Date=self.row.Scheduled_Start_Date + timedelta(days=1))),
        )

    def test_create_supplies_same_id_and_conference_version(self):
        self.events.get.return_value.execute.side_effect = http_error(404)
        self.assertEqual(main.upsert_calendar_event(self.service, self.row), "created")
        body = self.events.insert.call_args.kwargs["body"]
        self.assertEqual(body["id"], self.events.get.call_args.kwargs["eventId"])
        self.assertEqual(self.events.insert.call_args.kwargs["conferenceDataVersion"], 1)
        self.assertIn("conferenceData", body)
        self.events.patch.assert_not_called()

    def test_update_preserves_conference(self):
        self.assertEqual(main.upsert_calendar_event(self.service, self.row), "updated")
        self.assertNotIn("conferenceData", self.events.patch.call_args.kwargs["body"])
        self.assertEqual(self.events.patch.call_args.kwargs["eventId"], main.event_id_for_row(self.row))
        self.events.insert.assert_not_called()

    def test_get_auth_failure_never_attempts_insert(self):
        for status in (401, 403, 500):
            with self.subTest(status=status):
                self.events.get.return_value.execute.side_effect = http_error(status)
                with self.assertRaises(HttpError):
                    main.upsert_calendar_event(self.service, self.row)
        self.events.insert.assert_not_called()

    def test_concurrent_create_patches_same_id(self):
        self.events.get.return_value.execute.side_effect = http_error(404)
        self.events.insert.return_value.execute.side_effect = http_error(409)
        self.assertEqual(main.upsert_calendar_event(self.service, self.row), "updated")
        self.assertEqual(
            self.events.insert.call_args.kwargs["body"]["id"],
            self.events.patch.call_args.kwargs["eventId"],
        )

    def test_insert_denial_is_not_treated_as_existing_event(self):
        self.events.get.return_value.execute.side_effect = http_error(404)
        self.events.insert.return_value.execute.side_effect = http_error(403)
        with self.assertRaises(HttpError):
            main.upsert_calendar_event(self.service, self.row)
        self.events.patch.assert_not_called()

    def test_invalid_end_fails_before_insert(self):
        self.events.get.return_value.execute.side_effect = http_error(404)
        for end in (None, self.row.Scheduled_Start_Date, self.row.Scheduled_Start_Date - timedelta(hours=1)):
            with self.subTest(end=end):
                with self.assertRaises(ValueError):
                    main.upsert_calendar_event(self.service, maintenance_row(Scheduled_End_Date=end))
        self.events.insert.assert_not_called()


class PipelineTests(unittest.TestCase):
    @patch.object(main, "get_bq_client")
    @patch.object(main, "get_calendar_service")
    def test_auth_check_mode_never_queries_or_syncs(self, calendar, bq):
        response, status = main.sync_maintenance_to_calendar(
            SimpleNamespace(args={"mode": "check-auth"})
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "AUTHORIZED")
        self.assertEqual(response["user"], calendar_auth.EXPECTED_USER_EMAIL)
        self.assertEqual(response["calendar_id"], main.CALENDAR_ID)
        bq.assert_not_called()
        calendar.return_value.events.assert_not_called()

    @patch.object(main, "get_bq_client")
    @patch.object(main, "get_calendar_service", side_effect=calendar_auth.CalendarAuthError("no consent"))
    def test_auth_failure_stops_before_bigquery(self, calendar, bq):
        with self.assertRaises(calendar_auth.CalendarAuthError):
            main.sync_maintenance_to_calendar(None)
        bq.assert_not_called()

    @patch.object(main, "log_pipeline_run")
    @patch.object(main, "upsert_calendar_event")
    @patch.object(main, "get_bq_client")
    @patch.object(main, "get_calendar_service")
    def test_success_and_partial_failure_http_status(self, calendar, bq, upsert, log_run):
        for result, status, code in (
            ("created", "SUCCESS", 200),
            ("updated", "SUCCESS", 200),
            (ValueError("invalid end"), "PARTIAL_FAILURE", 500),
        ):
            with self.subTest(result=result):
                bq.return_value.query.return_value.result.return_value = [maintenance_row()]
                upsert.side_effect = result if isinstance(result, Exception) else None
                upsert.return_value = result
                response, http_status = main.sync_maintenance_to_calendar(None)
                self.assertEqual(response["status"], status)
                self.assertEqual(http_status, code)
                self.assertEqual(response["rows_processed"], 1)
                self.assertEqual(log_run.call_args.kwargs["status"], status)

    @patch.object(main, "log_pipeline_run")
    @patch.object(main, "upsert_calendar_event", side_effect=http_error(403))
    @patch.object(main, "get_bq_client")
    @patch.object(main, "get_calendar_service")
    def test_write_auth_failure_stops_run(self, calendar, bq, upsert, log_run):
        bq.return_value.query.return_value.result.return_value = [maintenance_row(), maintenance_row()]
        with self.assertRaises(calendar_auth.CalendarAuthError):
            main.sync_maintenance_to_calendar(None)
        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(log_run.call_args.kwargs["status"], "FAILED")


class AuthorizationSetupTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import mock_open

        patches = (
            patch("sys.argv", ["authorize.py", "--client-secrets", "client.json"]),
            patch("builtins.open", mock_open(read_data='{"installed":{}}')),
            patch.object(authorize, "InstalledAppFlow"),
            patch.object(authorize, "verified_user_credentials"),
            patch.object(authorize.secretmanager, "SecretManagerServiceClient"),
            patch.object(authorize, "build"),
            patch.object(authorize, "require_calendar_write_access"),
        )
        mocks = [item.start() for item in patches]
        for item in patches:
            self.addCleanup(item.stop)
        _, _, self.flow, self.verify, self.secret, self.build, self.access = mocks
        self.flow_credentials = self.flow.from_client_config.return_value.run_local_server.return_value
        self.flow_credentials.client_id = "test-client"
        self.flow_credentials.client_secret = "test-secret"
        self.flow_credentials.refresh_token = "test-refresh"

    def test_only_verified_user_grant_saved_without_access_token(self):
        authorize.main()
        self.verify.assert_called_once()
        self.flow.from_client_config.assert_called_once_with(
            {"installed": {}}, scopes=calendar_auth.OAUTH_SCOPES, autogenerate_code_verifier=True
        )
        request = self.secret.return_value.add_secret_version.call_args.kwargs["request"]
        info = json.loads(request["payload"]["data"])
        self.assertEqual(info["type"], "authorized_user")
        self.assertEqual(info["refresh_token"], "test-refresh")
        self.assertNotIn("token", info)
        self.build.assert_called_once_with(
            "calendar", "v3", credentials=self.verify.return_value, cache_discovery=False
        )

    def test_identity_or_scope_failure_never_publishes(self):
        self.verify.side_effect = calendar_auth.CalendarAuthError("wrong identity")
        with self.assertRaises(calendar_auth.CalendarAuthError):
            authorize.main()
        self.secret.assert_not_called()

    def test_verified_grant_survives_target_access_failure_but_command_fails(self):
        self.access.side_effect = calendar_auth.CalendarAuthError("wrong calendar ID")
        with self.assertRaisesRegex(calendar_auth.CalendarAuthError, "wrong calendar ID"):
            authorize.main()
        self.secret.return_value.add_secret_version.assert_called_once()


class DeploymentTests(unittest.TestCase):
    def test_archive_contains_only_runtime_and_canonical_shared_sources(self):
        with zipfile.ZipFile(io.BytesIO(deploy.source_archive())) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "main.py", "calendar_auth.py", "requirements.txt",
                    "shared/__init__.py", "shared/logging_config.py", "shared/pipeline_runs_logger.py",
                },
            )
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                self.assertGreater(archive.getinfo(name).file_size, 0)
            canonical_shared = deploy.FUNCTION_DIRECTORY.parents[2] / "shared" / "pipeline_runs_logger.py"
            self.assertEqual(archive.read("shared/pipeline_runs_logger.py"), canonical_shared.read_bytes())

    @patch.object(deploy, "operator_session")
    @patch.object(deploy, "api_json")
    @patch.object(deploy.requests, "put")
    def test_deployment_preserves_environment_and_only_patches_source_and_settings(self, put, api, operator):
        current = {"serviceConfig": {"environmentVariables": {"EXISTING_SETTING": "keep"}}}
        upload = {
            "uploadUrl": "https://storage.googleapis.com/test-signed-upload",
            "storageSource": {"bucket": "test-bucket", "object": "source.zip"},
        }
        api.side_effect = [
            current, upload, {"name": "operations/test", "done": True},
            {"state": "ACTIVE", "serviceConfig": {"revision": "test-revision"}},
        ]
        put.return_value.ok = True
        deploy.deploy()
        patch_call = api.call_args_list[2]
        self.assertEqual(patch_call.args[1], "PATCH")
        payload = patch_call.kwargs["json"]
        self.assertEqual(set(payload["serviceConfig"]), {"environmentVariables"})
        self.assertEqual(payload["serviceConfig"]["environmentVariables"]["EXISTING_SETTING"], "keep")
        self.assertEqual(payload["buildConfig"]["source"], {"storageSource": upload["storageSource"]})
        self.assertNotIn("Authorization", put.call_args.kwargs["headers"])

    @patch.object(deploy, "operator_session")
    @patch.object(deploy, "api_json")
    @patch.object(deploy.requests, "put")
    def test_upload_failure_never_patches_function(self, put, api, operator):
        api.side_effect = [
            {"serviceConfig": {}},
            {"uploadUrl": "https://storage.googleapis.com/test", "storageSource": {}},
        ]
        put.return_value.ok = False
        put.return_value.status_code = 403
        with self.assertRaisesRegex(RuntimeError, "Source upload failed"):
            deploy.deploy()
        self.assertEqual(api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
