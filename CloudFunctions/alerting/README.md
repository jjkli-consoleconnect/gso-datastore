# Pipeline Error Alerting (A – log-based)

Alerts to **Slack** (via the `gsodatapipe-error-notification` Slack email alias) whenever a
monitored data pipeline Cloud Function logs an ERROR-level entry **or** an exception/error
phrase — i.e. the "script failed" case.

Stack (all created/tracked in GCP, driven by `setup_alerts.py`):

| Piece | GCP service | Name |
|---|---|---|
| Log-based metric | Cloud Logging | `pipeline_error_count` |
| Notification channel | Cloud Monitoring | email -> Slack alias |
| Alert policy | Cloud Monitoring | `Pipeline errors (GS-Slack)` |

## What it catches (and why it's phrase-based)
Gen2 Cloud Functions log under `cloud_run_revision`. Those using `logging.basicConfig()`
write to **stderr** (=> `severity=ERROR`), but several pipelines use an stdout
`StreamHandler` (=> `severity=INFO`). A severity-only filter would silently miss them, so
the metric matches:

```
resource.type="cloud_run_revision"
AND resource.labels.service_name IN (monitored functions)
AND ( severity >= ERROR  OR  textPayload =~ "(?i)(stacktrace|traceback (most recent call last)|pipeline error|cloud function failed|function failed|error merging|unexpected error|failed to |exception)" )
```

## Projects / functions monitored
- `pccw-internal-virt-agent-uat` (9 data pipelines): process-bq-hdwl-email,
  process-bq-bmc-user-list-email, process-shr-people-email, process-snapshot-reports-email,
  process-training-data-email, process-srinventory-email, process-handover-email,
  sync_pagerduty_incidents, gmail-checker-oauth.
- `pccw-internal-virtual-agent` (13 Jira/Helix): jira-tickets-sync(+nightly),
  jira-tickets(+nightly), jira-changelog-sync(+nightly), jira-changelogs-sync(+nightly),
  jira-comments-sync(+nightly), jira-comments-nightly, jira-to-helix-create-prod,
  mss-to-remedy-create-prod.

## Use

Create / reapply (idempotent — safe to re-run):
```
py -3 setup_alerts.py
```
Requires a `gcloud` login with Logging/Monitoring admin on both projects (uses
`gcloud auth print-access-token`; no pip deps).

## Adding / removing a monitored function
Edit `PROJECT_SERVICES` in `setup_alerts.py` and re-run. The metric filter is rebuilt,
but note the **metric is not auto-replaced on re-run** (it only creates on missing). To
materialize a changed filter: delete the metric + policy in the project, then re-run:
```
# delete metric (Logging) and alert policy (Monitoring), then:
py -3 setup_alerts.py
```

## Verify / teardown
- Verify in the console: Logging -> Metrics, Monitoring -> Alerting.
- Alerts fire only when a monitored function genuinely logs an error after the metric
  exists (it counts new entries, so past errors won't page).
- Remove: delete the alert policy, then the metric, then the notification channel(s)
  referencing the Slack alias.

## Next (not done here)
- **Stopped / skipped** detection needs a scheduled monitor scanning `GSO.PipelineRuns`
  for stale `RUNNING` rows and missing heartbeats — logs alone can't catch "never ran".
