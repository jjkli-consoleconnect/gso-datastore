# pipeline_daily_report

Daily health summary for the **GS data-pipe pipelines**, driven by the shared
`GSO.PipelineRuns` table. Emailed to the `gsodatapipe-error-notification` Slack
alias every morning.

## What it flags (previous 24h)
| Code | Meaning |
|------|---------|
| `FAILED` | a run with Status `ERROR` / `FAILED` (shows the log message) |
| `STALLED` | a run stuck in `RUNNING` longer than ~3x its cadence (or 2h) |
| `LOW_ROWS` | a `SUCCESS` run that merged fewer rows than an opt-in `min_rows` threshold |
| `MISSED` | an active pipeline silent for ~1.6x its **own** median inter-run gap |

Cadence is **self-tuning**: each pipeline's typical gap is measured from the last
14 days of `PipelineRuns`, so HDWL (~every 2.5 min) and a nightly pipe (once a day)
are both handled without a hand-maintained schedule. Sparse/new pipelines (few runs)
are not false-flagged.

Daily-ish pipelines with bursty Pub/Sub delivery, like `pubsub - SHRPeople`, use
explicit `expected_interval_hours` overrides so a small retry/burst cluster does not
teach the report that the pipeline should run every few minutes.

`SUCCESS` runs with `RowsMerged=0` are treated as idle successful runs by default.
For incremental pipelines such as Jira, that usually means the source had no new
matching changes in that run window, not that sync data was missed. Only pipelines
with a configured `min_rows` threshold are flagged as `LOW_ROWS`.

## Files
- `main.py` — the Cloud Function (HTTP entrypoint `main`; has a `__main__` smoke test).
- `requirements.txt` — runtime deps (matches other CFs).
- `deploy.sh` — deploys the function + Cloud Scheduler (daily 09:00 HKT).

## Env / grants needed
1. BigQuery: function reads `pccw-internal-virt-agent-uat.GSO.PipelineRuns`.
2. Secret Manager: reads `gmail-oauth-token` and sends via Gmail API.
   - **Important:** the OAuth token must include the `gmail.send` scope for delivery
     to work. The existing pipelines use the same token for reads only — verify scope
     before relying on the email.
3. Service account: e.g. `pipeline-report@{project}.iam.gserviceaccount.com` with
   `roles/bigquery.dataViewer`, `roles/secretmanager.secretAccessor`.

## Deploy
```
SERVICE_ACCOUNT=service-account@project.iam.gserviceaccount.com ./deploy.sh
```
(Adjust `PROJECT_ID`/`SERVICE_ACCOUNT`/`SCHEDULE` inside `deploy.sh` as needed.)

## Local smoke test of the logic
```
py -3 main.py
```
requires BQ/Auth locally. Or run `_test_logic.py` with stubbed deps (no cloud creds)
to see fabricated example output.

## Tuning
Edit `PIPELINE_OVERRIDES` in `main.py`:

```
"pubsub - SHRPeople": {"expected_interval_hours": 24}
"some required-volume pipe": {"min_rows": 1}
```

Keep `DEFAULT_MIN_ROWS=0` unless most pipelines should treat idle successful runs
as anomalies.