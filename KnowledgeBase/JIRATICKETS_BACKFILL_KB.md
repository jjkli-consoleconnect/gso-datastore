# JiraTickets Backfill — LLM Runbook

How to backfill tickets into BigQuery from a CSV export (or API), fast, without hitting the same roadblocks twice. Written after the AS3491 backfill (2026-08).

## Targets

| Thing | Value |
|---|---|
| UAT project | `pccw-internal-virt-agent-uat` (**NOT** `pccw-internal-virtual-agent-uat` — that name 404s) |
| Prod project | `pccw-internal-virtual-agent` |
| Tickets table | `<project>.GSO.JiraTickets` |
| Progress table | `<project>.GSO.JiraTickets_progress` (cols: WindowStart, WindowEnd, Status, LastRun, Project, RowCount) |
| Service account (UAT) | `G:\My Drive\serviceaccount\pccw-internal-virt-agent-uat-1a19f8759266.json` |
| BQ python lib | `google-cloud-bigquery`, works locally. `bq` CLI mostly fails/ambiguous here — use Python client |

## Roadblocks and how to skip them

### 1. PowerShell + python quoting hell
Do NOT try to run inline `python -c "..."` with quotes inside a PowerShell command — nested quote escaping will eat 3+ tool calls. Instead:
1. Write the script with the `editor` tool (`Set old_text=""` to create).
2. Run it via `[System.Diagnostics.Process]::Start()` with `$psi.EnvironmentVariables['GOOGLE_APPLICATION_CREDENTIALS']=<sa path>` — plain `python script.py` in run_commands picks up no creds and PowerShell stderr-to-stdout redirection throws NativeCommandError noise.

Template that works:
```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName='python'; $psi.Arguments='-X utf8 <script>.py'
$psi.WorkingDirectory='G:\My Drive\Scripts\CloudFunctions'
$psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true; $psi.UseShellExecute=$false
$psi.EnvironmentVariables['GOOGLE_APPLICATION_CREDENTIALS']='G:\My Drive\serviceaccount\pccw-internal-virt-agent-uat-1a19f8759266.json'
$proc=[System.Diagnostics.Process]::Start($psi)
$out=$proc.StandardOutput.ReadToEnd(); $err=$proc.StandardError.ReadToEnd(); $proc.WaitForExit()
"EXIT=$($proc.ExitCode)"; $out; ($err -split "`n") | Select-Object -Last 5
```
If the job may exceed 30s (loads/MERGEs do): launch detached (`cmd /c start /b ... > out.txt 2> err.txt`), then poll by reading the log files in a follow-up call.

### 2. Jira CSV export caps at 10,000 rows — SILENTLY
The UI export just drops older issues past 10k, newest-first. First sign: expected ticket count >> row count.
**Diagnose** (30s): extract issue numbers from `Issue key`, sort, check min/max/gaps:
```
count=10000, min=4372, max=14572, ~106 small gaps = deleted issues (normal)
min >> 1  => export truncated; oldest (key-1) records missing
```
**Fix:** re-export with `created < "<created date of lowest loaded key>"`. Cross-check boundary date via `SELECT MIN(Created)` on loaded rows.

### 3. Schema source of truth
Don't guess column names. Two sources:
- Live table: `client.get_table("<proj>.GSO.JiraTickets").schema`
- Field-mapping reference (how each field is derived from Jira): `JiraTicketsNightly\main.py` → `bq_schema` list (~line 1107) + `build_ticket_row()` (~line 829)

Mapping notes for Jira CSV exports ("Atlassian CSV" format):
- Multi-value fields repeat as duplicate header columns (`Components`, `Labels`, links...) — collect by matching header text, not index.
- `SR Ref` lives in `Custom field (SR Ref)` (~709 fill for AS3491).
- Remedy number: use `Custom field (Remedy Ticket Number (migrated))`.
- Root cause: only `Custom field (Root Causes)` populated (plural). Many similar-named empties exist — check fill rates before mapping.
- Jira timestamps like `Aug 27, 2026 14:40`; DueDate can be `Aug 27, 2026 00:00` even though it's a DATE column.
- Array columns (Labels, Component, RemedyTicketNumber): pass a JSON **list**, not comma-joined string. Nullables need explicit `None`, never `""`.

### 4. Safe MERGE pattern (never clobber, never dupe)
Stage into temp table (`WRITE_APPEND`, schema copied from target), then dedupe-in-source and guard-vs-target:
```sql
MERGE `T` TGT
USING (SELECT *, ROW_NUMBER() OVER (PARTITION BY Key ORDER BY Updated DESC) rn
       FROM temp WHERE rn=1 AND Key IS NOT NULL AND TRIM(Key)<>'') S
ON TGT.Key=S.Key AND (S.Updated IS NULL OR TGT.Updated IS NULL OR S.Updated >= TGT.Updated)
WHEN MATCHED THEN UPDATE SET <COALESCE per col; IF(S.x IS NULL,...) for arrays>
WHEN NOT MATCHED THEN INSERT ...
```
The `S.Updated >= TGT.Updated` guard means you can overlap exports freely — newer prod-synced rows win. Verify afterwards with `SELECT COUNT(*) WHERE Key LIKE '<PREFIX>-%'`.

### 5. Nightly must NOT redo the backfill
After loading, write/update the progress marker so `JiraTicketsNightly` resumes forward-only:
```json
{"Project": "<exact Jira project name, e.g. IPE AS3491>",
 "WindowStart": "<true MIN(Created) across ALL backfilled batches>",
 "WindowEnd": "<max(Updated)+5min, rounded>",
 "Status": "complete", "RowCount": N,
 "LastRun": "<now UTC>"}
```
DELETE the existing Project row first, then insert.
⚠️ If you backfill OLDER data later, also UPDATE `WindowStart` backwards — otherwise nightly thinks history starts at the first batch's date.

### 6. Working example
Reusable script from last run: `G:\My Drive\Scripts\Temp\AS3491\backfill_as3491.py` — copy it into a work-item folder under `Temp`, then change `CSV_PATH`, key prefix, progress Project name. It already does: parse→dedupe-by-Key-keep-newest→schema-check-vs-live-table→temp load in 2000-row chunks→guarded MERGE→progress upsert→temp drop.

## Quick checklist
1. CSV present? Row count sane vs expected total? Key-gap scan if not.
2. Confirm creds env var + table IDs (UAT vs prod!).
3. Copy/adapt `Temp/AS3491/backfill_as3491.py`; check fill rates before trusting customfield mappings.
4. Run detached; poll logs.
5. Verify count in BQ.
6. Upsert progress marker (fix WindowStart if going further back).
7. Clean up scratch scripts/logs.
