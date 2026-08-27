from types import SimpleNamespace

from google.api_core.exceptions import NotFound

import shared.secrets_manager as secrets_manager


class FakeClient:
    def __init__(self):
        self.calls = []

    def list_secret_versions(self, request=None):
        return [
            SimpleNamespace(
                name="projects/demo/secrets/jira-api-token/versions/3",
                state=SimpleNamespace(name="DESTROYED"),
            ),
            SimpleNamespace(
                name="projects/demo/secrets/jira-api-token/versions/2",
                state=SimpleNamespace(name="ENABLED"),
            ),
            SimpleNamespace(
                name="projects/demo/secrets/jira-api-token/versions/1",
                state=SimpleNamespace(name="ENABLED"),
            ),
        ]

    def access_secret_version(self, request=None):
        name = request["name"]
        self.calls.append(name)
        if name.endswith("/versions/latest"):
            raise NotFound("latest alias is destroyed")
        if name.endswith("/versions/2"):
            return SimpleNamespace(payload=SimpleNamespace(data=b"fallback-token"))
        raise NotFound("unexpected version")


def test_get_secret_falls_back_to_latest_enabled_version(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        secrets_manager.secretmanager,
        "SecretManagerServiceClient",
        lambda: fake_client,
    )

    value = secrets_manager.get_secret("jira-api-token", project_id="demo")

    assert value == "fallback-token"
    assert fake_client.calls == [
        "projects/demo/secrets/jira-api-token/versions/latest",
        "projects/demo/secrets/jira-api-token/versions/2",
    ]
