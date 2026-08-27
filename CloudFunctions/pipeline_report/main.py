#!/usr/bin/env python3
"""
pipeline_daily_report -- scheduled Cloud Function (gen2, HTTP).

Each morning it reads the shared `GSO.PipelineRuns` table in the UAT project and
sends one summary email to the GS data-pipe Slack alias listing abnormalities
from the previous 24h:

  FAILED   runs (Status ERROR / FAILED)
  STALLED  a run left RUNNING too long (stuck/timeout)
  ZERO     a successful run that merged rows below its threshold
  MISSED   an active pipeline silent for ~1.6x its *own* historical gap

Because all pipelines log to one table yet cadences differ wildly (HDWL ~every
couple minutes, Jira hourly, others rare), code measures each pipeline's median
inter-run gap over the past N days instead of a hand-maintained manifest.

Trigger: Cloud Scheduler -> HTTP gen2 function (see deploy.sh + scheduler cmd).
Sends via Gmail API using the shared OAuth cred (secret: gmail-oauth-token).
"""

import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import functions_framework
from email.mime.text import MIMEText
from google.cloud import secretmanager, bigquery

logger = logging.getLogger("pipeline_report")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------ config --
PROJECT_ID = "pccw-internal-virt-agent-uat"
TABLE_REF = "pccw-internal-virt-agent-uat.GSO.PipelineRuns"

NOTIFICATION_EMAIL = (
    "gsodatapipe-error-not-aaaavviyu3xteme3fxe6i2jkpe@consoleconnect.org.slack.com"
)

LOOKBACK_DAYS = 14  # window used to learn each pipeline's cadence
REPORT_HOURS = 24  # window we report on

# Per-pipeline overrides keyed by exact PipelineName in GSO.PipelineRuns.
#   {"min_rows": N} flags SUCCESS runs with RowsMerged < N.
PIPELINE_OVERRIDES = {
    # "pubsub - HDWL": {"min_rows": 1},
}

# A SUCCESS run is "zero rows" when RowsMerged is below this (unless overridden).
DEFAULT_MIN_ROWS = 1


# ------------------------------------------------------------------ helpers --
def _get(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_rows(client, lookback_days=LOOKBACK_DAYS):
    sql = f"""
        SELECT PipelineName, RunTime, Status, RowsMerged, Message
        FROM `{TABLE_REF}`
        WHERE RunTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", lookback_days)
            ]
        ),
    )
    out = []
    for r in job.result():
        out.append(
            {
                "pipeline": _get(r, "PipelineName", "Unknown") or "Unknown",
                "run_ts": _as_dt(_get(r, "RunTime", None)),
                "status": str(_get(r, "Status", "") or "").strip().upper(),
                "rows": _get(r, "RowsMerged", None),
                "msg": str(_get(r, "Message", "") or ""),
            }
        )
    return out


def median_gap_seconds(timestamps):
    ts = sorted(t for t in timestamps if t is not None)
    if len(ts) < 2:
        return None
    gaps = sorted((ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1))
    m = len(gaps) // 2
    return gaps[m] if len(gaps) % 2 == 1 else (gaps[m - 1] + gaps[m]) / 2.0


def analyze(rows, now):
    """Return (overview, issues)."""
    cutoff = now - timedelta(hours=REPORT_HOURS)
    by_pipe = {}
    for r in rows:
        by_pipe.setdefault(r["pipeline"], []).append(r)

    overview = {}
    issues = []

    for pipe, runs in by_pipe.items():
        runs.sort(
            key=lambda r: r["run_ts"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        times = [r["run_ts"] for r in runs]
        last = times[0] if times else None
        gap = median_gap_seconds(times)
        runs_24h = sum(1 for t in times if t and t >= cutoff)
        overview[pipe] = {
            "runs_24h": runs_24h,
            "last_run": last,
            "age_h": ((now - last).total_seconds() / 3600.0) if last else None,
            "gap_sec": gap,
        }

        # FAILED / ERROR in window
        for r in runs:
            if not r["run_ts"] or r["run_ts"] < cutoff:
                continue
            if r["status"] in ("ERROR", "FAILED"):
                issues.append(
                    {
                        "type": "FAILED",
                        "pipeline": pipe,
                        "when": r["run_ts"],
                        "detail": (r["msg"] or "no error message")[:300],
                    }
                )

        # ZERO rows on success below threshold
        min_rows = PIPELINE_OVERRIDES.get(pipe, {}).get("min_rows", DEFAULT_MIN_ROWS)
        for r in runs:
            if (
                not r["run_ts"]
                or r["run_ts"] < cutoff
                or r["status"] != "SUCCESS"
                or r["rows"] is None
            ):
                continue
            if r["rows"] < min_rows:
                issues.append(
                    {
                        "type": "ZERO",
                        "pipeline": pipe,
                        "when": r["run_ts"],
                        "detail": "merged %s rows (min %s)" % (r["rows"], min_rows),
                    }
                )

        # STALLED: RUNNING left open far beyond cadence
        for r in runs:
            if r["status"] != "RUNNING" or not r["run_ts"]:
                continue
            age_sec = (now - r["run_ts"]).total_seconds()
            tol = max(3 * (gap or 3600), 2 * 3600)
            if age_sec > tol:
                issues.append(
                    {
                        "type": "STALLED",
                        "pipeline": pipe,
                        "when": r["run_ts"],
                        "detail": "RUNNING for %.1fh without completion"
                        % (age_sec / 3600.0),
                    }
                )

        # MISSED: active pipeline silent for ~1.6x its own gap
        if gap and len(times) >= 6 and last:
            age_sec = (now - last).total_seconds()
            if age_sec >= 1.6 * gap:
                issues.append(
                    {
                        "type": "MISSED",
                        "pipeline": pipe,
                        "when": last,
                        "detail": "silent %.1fh (expected ~every %.1fh)"
                        % (age_sec / 3600.0, gap / 3600.0),
                    }
                )

    return overview, issues


def build_report_text(overview, issues, now):
    lines = []
    lines.append("GSO DataPipe daily report - " + now.strftime("%Y-%m-%d"))
    lines.append("=" * 50)
    lines.append("")
    lines.append("Pipelines tracked: %d" % len(overview))
    lines.append("Issues found:      %d" % len(issues))
    lines.append("")
    if issues:
        lines.append("ISSUES")
        lines.append("------")
        for it in issues:
            when = it["when"].strftime("%H:%M") if it["when"] else "-"
            lines.append(
                "[%s] %s @ %s | %s" % (it["type"], it["pipeline"], when, it["detail"])
            )
        lines.append("")
    else:
        lines.append("All monitored pipelines healthy. Good job!")
        lines.append("")

    lines.append("SUMMARY (last %dh)" % REPORT_HOURS)
    lines.append("-" * 50)
    for pipe, m in sorted(overview.items()):
        last = m["last_run"].strftime("%m-%d %H:%M") if m["last_run"] else "never"
        gap = ("%s" % m["gap_sec"]) if m["gap_sec"] else "-"
        age = ("%.1f" % m["age_h"]) if m["age_h"] is not None else "-"
        lines.append(
            "%-34s runs=%-4s last=%-13s age(h)=%-6s gap(s)=%s"
            % (pipe, m["runs_24h"], last, age, gap)
        )
    lines.append("")
    lines.append(
        "Healthy pipelines: %d"
        % len([p for p in overview if not any(i["pipeline"] == p for i in issues)])
    )
    return "\n".join(lines)


def get_gmail_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client = secretmanager.SecretManagerServiceClient()
    secret_name = "projects/%s/secrets/gmail-oauth-token/versions/latest" % PROJECT_ID
    resp = client.access_secret_version(request={"name": secret_name})
    token_data = json.loads(resp.payload.data.decode("UTF-8"))
    creds = Credentials.from_authorized_user_info(token_data)
    return build("gmail", "v1", credentials=creds)


def send_email(subject, body, to=NOTIFICATION_EMAIL):
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    service = get_gmail_service()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("sent report email -> %s", to)


@functions_framework.http
def main(request):
    try:
        now = datetime.now(timezone.utc)
        client = bigquery.Client(project=PROJECT_ID)
        rows = fetch_rows(client)
        overview, issues = analyze(rows, now)
        body = build_report_text(overview, issues, now)
        subject = "[DataPipe %s] %d anomaly(-ies)" % (
            now.strftime("%Y-%m-%d"),
            len(issues),
        )
        send_email(subject, body)
        return "%s\n%s" % (subject, body), 200
    except Exception as exc:
        logger.exception("pipeline_report failed")
        return "ERROR: %s" % exc, 500


if __name__ == "__main__":
    import sys

    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    now = datetime.now(timezone.utc)
    client = bigquery.Client(project=PROJECT_ID)
    rows = fetch_rows(client)
    overview, issues = analyze(rows, now)
    print(build_report_text(overview, issues, now))
