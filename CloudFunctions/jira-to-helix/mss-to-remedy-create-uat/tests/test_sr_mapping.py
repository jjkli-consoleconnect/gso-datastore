import importlib.util
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "main.py"
spec = importlib.util.spec_from_file_location("jira_to_helix_uat_main", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sr_mapping_adds_related_entity_and_assigned_group():
    jira_issue = {
        "fields": {
            "summary": "Test",
            "description": "Test description",
            "customfield_20270": "TMS",
        }
    }

    payload = module.map_jira_to_helix(jira_issue, "MSS-1", "TMS", "SR135227")

    assert payload["assignedGroup"] == "ASOC"
    assert any(
        entity.get("role") == "srId" and entity.get("name") == "SR135227"
        for entity in payload.get("relatedEntity", [])
    )


def test_resolve_jira_issue_for_mapping_fetches_full_issue_when_webhook_fields_are_incomplete(monkeypatch):
    webhook_issue = {
        "fields": {
            "summary": "Test",
            "status": {"name": "Resolved"},
        }
    }
    full_issue = {
        "fields": {
            "summary": "Test",
            "customfield_20270": "TMSTKL",
            "customfield_10228": "SR128190",
        }
    }

    def fake_get_jira_issue(jira_key, jira_url):
        assert jira_key == "MSS-1"
        assert jira_url == "https://example.test"
        return full_issue

    monkeypatch.setattr(module, "get_jira_issue", fake_get_jira_issue)

    resolved = module.resolve_jira_issue_for_mapping(webhook_issue, "MSS-1", "https://example.test")

    assert resolved == full_issue


def test_map_jira_to_helix_sets_resolved_status_for_resolved_jira_issue():
    jira_issue = {
        "fields": {
            "summary": "Resolved test ticket",
            "description": "Test description",
            "status": {"name": "Resolved"},
            "customfield_20270": "TMSTKL",
            "customfield_10878": "SR128190",
        }
    }

    payload = module.map_jira_to_helix(jira_issue, "MSS-1611", "TMSTKL", "SR128190")

    assert payload["status"] == "RESOLVED"


def test_extract_jira_sr_no_ignores_jira_fields_and_forces_default_sr():
    fields = {
        "customfield_10878": "SR999999",
        "customfield_10228": "SR000001",
        "customfield_11510": "SR777777",
    }

    assert module.extract_jira_sr_no(fields) == "SR128190"
