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

    payload = module.map_jira_to_helix(jira_issue, "MSS-1")

    assert payload["assignedGroup"] == "ASOC"
    assert any(
        entity.get("role") == "srId" and entity.get("name") == "SR128190"
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


def test_map_jira_to_helix_ignores_jira_customer_and_uses_default_pair():
    jira_issue = {
        "fields": {
            "summary": "Default pair test",
            "description": "Default pair test",
            "customfield_11247": "VOLTSA",
            "customfield_20270": "TMSTKL",
            "customfield_10878": "SR999999",
        }
    }

    payload = module.map_jira_to_helix(jira_issue, "MSS-1613")

    assert payload["assignedGroup"] == "ASOC"
    assert payload.get("relatedEntity", []) == [
        {
            "name": "TMSTKL",
            "role": "customerId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
        {
            "name": "SR128190",
            "role": "srId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
    ]


def test_map_jira_to_helix_falls_back_to_required_defaults_when_values_are_empty():
    jira_issue = {
        "fields": {
            "summary": "Fallback test",
            "description": "Fallback description",
        }
    }

    payload = module.map_jira_to_helix(jira_issue, "MSS-1612")

    assert payload["assignedGroup"] == "ASOC"
    assert payload.get("relatedEntity", []) == [
        {
            "name": "TMSTKL",
            "role": "customerId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
        {
            "name": "SR128190",
            "role": "srId",
            "@type": "RelatedEntity",
            "@referredType": "Profile",
        },
    ]
    assert payload.get("notes", []) == [
        {
            "id": "category",
            "@type": "faultsymptom",
            "text": "Others",
        },
        {
            "id": "item",
            "@type": "faultsymptom",
            "text": "Others",
        },
        {
            "id": "type",
            "@type": "faultsymptom",
            "text": "Others",
        },
    ]


def test_map_jira_to_helix_includes_jira_source_metadata_in_description():
    jira_issue = {
        "fields": {
            "summary": "Traceability test",
            "description": "Original description",
            "created": "2026-08-01T12:34:56.000+0000",
            "updated": "2026-08-02T13:14:15.000+0000",
            "resolutiondate": "2026-08-03T14:15:16.000+0000",
            "assignee": {"displayName": "Ada Lovelace"},
            "resolution": {"name": "Done"},
            "customfield_11247": "VOLTSA",
            "customfield_10878": "SR999999",
        }
    }

    payload = module.map_jira_to_helix(jira_issue, "MSS-1614")

    description = payload.get("description", "")
    assert "[Jira Source Trace]" in description
    assert "Jira customer ID: VOLTSA" in description
    assert "Jira SR no: SR999999" in description
    assert "[Jira Source Metadata]" in description
    assert "Jira Created: 2026-08-01T12:34:56Z" in description
    assert "Jira Updated: 2026-08-02T13:14:15Z" in description
    assert "Jira Resolved: 2026-08-03T14:15:16Z" in description
    assert "Jira Assignee: Ada Lovelace" in description
    assert "Jira Resolution: Done" in description
    assert "Helix customerId:" not in description
    assert "Helix srId:" not in description
