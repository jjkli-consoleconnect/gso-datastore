#!/usr/bin/env python3
"""
GCP pipeline-error alerting bootstrap.

Per project, creates the pieces needed so a failing Cloud Function pages the
configured Slack alias:
  1. Logging log-based metric (counts ERROR-level / error-phrase log entries)
  2. Monitoring notification channel (email -> Slack alias)
  3. Monitoring alert policy (metric > 0 in 5 min -> notify that channel)

Why not severity-only: gen2 functions log under cloud_run_revision. Those using
logging.basicConfig() write to stderr (=> ERROR severity) but others use a
stdout StreamHandler (=> INFO severity), so a severity-only filter silently
misses them.  The metric therefore matches  severity>=ERROR  OR  an error
phrase in the payload, covering both logging styles.

Idempotent: existing metric/channel/policy are reused.  Stdlib only (urllib +
gcloud token) => no pip install.

Usage:  python setup_alerts.py
"""

import json
import subprocess
import urllib.request
import urllib.error

# ------------------------------ config ----------------------------------
SLACK_CHANNEL = (
    "gsodatapipe-error-not-aaaavviyu3xteme3fxe6i2jkpe@consoleconnect.org.slack.com"
)

PROJECT_SERVICES = {
    "pccw-internal-virt-agent-uat": [
        "process-bq-hdwl-email",
        "process-bq-bmc-user-list-email",
        "process-shr-people-email",
        "process-snapshot-reports-email",
        "process-training-data-email",
        "process-srinventory-email",
        "process-handover-email",
        "sync_pagerduty_incidents",
        "gmail-checker-oauth",
    ],
    "pccw-internal-virtual-agent": [
        "jira-tickets-sync",
        "jira-tickets-sync-nightly",
        "jira-tickets",
        "jira-tickets-nightly",
        "jira-changelog-sync",
        "jira-changelog-sync-nightly",
        "jira-changelogs-sync",
        "jira-changelogs-nightly",
        "jira-comments-sync",
        "jira-comments-sync-nightly",
        "jira-comments-nightly",
        "jira-to-helix-create-prod",
        "mss-to-remedy-create-prod",
    ],
}

METRIC_ID = "pipeline_error_count"  # short id -> "logging.googleapis.com/user/<id>"
POLICY_DISPLAY = "Pipeline errors (GS-Slack)"
ALIGNMENT_PERIOD = "300s"

# Error phrases matched on the payload text (case-insensitive), for the
# stdout-handler style functions whose entries do NOT carry severity=ERROR.
# Deliberately strict: broad words like "exception" / "failed to" also appear
# in benign lines (retryable warnings, customer email bodies dumped to logs).
PHRASE_RE = (
    r"(?i)(stacktrace|traceback \(most recent call last\)|pipeline error"
    r"|cloud function failed|function failed|error merging|unexpected error)"
)

# Known-benign lines that must never count, even if they contain a phrase
# above. Kept in one place so future noise just extends this list.
BENIGN_RE = (
    r"(?i)(insert exception attempt [123]/"
    r"|\[hpm\] subscribed"
    r"|content of note id)"
)


# ------------------------------ http helpers ------------------------------
def get_token():
    # gcloud is a .bat/.cmd shim on Windows; route through cmd.exe so the shim
    # is found even when Python subprocess doesn't inherit the PATH resolution.
    cmd = ["cmd", "/c", "gcloud", "auth", "print-access-token"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _do(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.fp.read().decode() if e.fp else str(e)}
    except Exception as e:
        return 0, {"_error": str(e)}


def _list_names(url, key, token):
    """Return set of names from a GCP list resource, or an empty set on error."""
    code, data = _do("GET", url, token)
    if code != 200:
        return set(), code, data
    return {m.get("name") for m in data.get(key, [])}, 200, None


# ------------------------------ builders ----------------------------------
def build_metric_filter(project, services):
    names = " OR ".join(f'resource.labels.service_name = "{s}"' for s in services)
    return (
        f'resource.type="cloud_run_revision" AND ({names}) '
        f'AND (severity >= ERROR OR textPayload =~ "{PHRASE_RE}") '
        f'AND NOT textPayload =~ "{BENIGN_RE}"'
    )


def build_policy_body(project, channel_name):
    return {
        "displayName": POLICY_DISPLAY,
        "combiner": "OR",
        "conditions": [
            {
                "displayName": "pipeline_error_count > 0 over 5 min",
                "conditionThreshold": {
                    "filter": f'metric.type="logging.googleapis.com/user/{METRIC_ID}" AND resource.type="cloud_run_revision"',
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0,
                    "duration": "0s",
                    "aggregations": [
                        {
                            "alignmentPeriod": ALIGNMENT_PERIOD,
                            "perSeriesAligner": "ALIGN_DELTA",
                            "crossSeriesReducer": "REDUCE_SUM",
                        }
                    ],
                },
            }
        ],
        "notificationChannels": [channel_name],
        "documentation": {
            "content": (
                "Pipeline error alert from log-based metric "
                f'"logging.googleapis.com/user/{METRIC_ID}" in project {project}.\n\n'
                "A monitored data-pipeline logged an ERROR entry or an exception/error "
                "phrase. Check Cloud Logging for the affected service."
            ),
            "mimeType": "text/markdown",
        },
    }


def api_url(project):
    return "https://monitoring.googleapis.com/v3/projects/{}".format(project)


# ------------------------------ run ----------------------------------------
def run():
    token = get_token()
    print(f"Token OK. Notifying -> {SLACK_CHANNEL}")

    for project, services in PROJECT_SERVICES.items():
        print(f"\n=== {project} ({len(services)} services) ===")

        # 1) log-based metric (always updated so filter refinements deploy)
        metric_api = f"https://logging.googleapis.com/v2/projects/{project}/metrics"
        names, code, _ = _list_names(metric_api, "metrics", token)
        metric_body = {
            "name": METRIC_ID,
            "description": "Pipeline error log entries per alignment window.",
            "filter": build_metric_filter(project, services),
            "metricDescriptor": {
                "metricKind": "DELTA",
                "valueType": "INT64",
                "unit": "1",
            },
        }
        if METRIC_ID in names:
            code, data = _do("PUT", f"{metric_api}/{METRIC_ID}", token, metric_body)
            print(
                "  [ok]  metric filter updated"
                if code == 200
                else f"  [FAIL] metric update {code} {data.get('_error')}"
            )
        else:
            code, data = _do("POST", metric_api, token, metric_body)
            print(
                "  [ok]  metric"
                if code in (200, 201)
                else f"  [FAIL] metric {code} {data.get('_error')}"
            )

        # 2) notification channel
        channel_api = api_url(project) + "/notificationChannels"
        code, data = _do("GET", channel_api, token)
        channel_name = None
        if code == 200:
            for ch in data.get("notificationChannels", []):
                if (
                    ch.get("type") == "email"
                    and ch.get("labels", {}).get("email_address") == SLACK_CHANNEL
                ):
                    channel_name = ch.get("name")
                    break
        if channel_name:
            print(f"  [skip] channel exists: {channel_name}")
        else:
            body = {
                "type": "email",
                "displayName": "GS DataPipe Error (Slack)",
                "labels": {"email_address": SLACK_CHANNEL},
            }
            code, data = _do("POST", channel_api, token, body)
            if code in (200, 201) and data.get("name"):
                channel_name = data["name"]
                print(f"  [ok]  channel: {channel_name}")
            else:
                print(f"  [FAIL] channel {code} {data.get('_error')}")
                continue

        # 3) alert policy
        policies_api = api_url(project) + "/alertPolicies"
        code, data = _do("GET", policies_api, token)
        exists = False
        if code == 200:
            exists = any(
                p.get("displayName") == POLICY_DISPLAY
                for p in data.get("alertPolicies", [])
            )
        if exists:
            print("  [skip] alert policy already exists")
        else:
            code, data = _do(
                "POST", policies_api, token, build_policy_body(project, channel_name)
            )
            print(
                "  [ok]  policy"
                if code in (200, 201)
                else f"  [FAIL] policy {code} {data.get('_error')}"
            )

    print("\nDone.")


if __name__ == "__main__":
    run()
