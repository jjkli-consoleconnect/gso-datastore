# BigQuery Sync (Pull/Push)

Minimal workflow to pull BigQuery objects (views, materialized views, routines) into versioned files and push changes back.

## Files
- `bq-sync.config.json` — configure projects/datasets, output path, and options.
- `pull.ps1` — export definitions from BigQuery to `outputDir`.
- `push.ps1` — update BigQuery from local files.

## Prereqs
- gcloud SDK + `bq` CLI installed and authenticated.
- Permission to read and update datasets/views/routines.

## Authentication
- Default: use your current `gcloud` / Application Default Credentials session. For local setup, run `gcloud auth login` and, if you also use Python Google client libraries, `gcloud auth application-default login`.
- Optional local override: create `BigQuerySync/bq-sync.config.local.json` and put `credentialsFile` there if you absolutely need a key file. Keep that file outside git.
- Do not store credential JSON files in this repo.

## Quick start
1. Edit `bq-sync.config.json` (projects, datasets, outputDir, location).
2. Pull: use VS Code task `BigQuery: Pull` or run `./pull.ps1`.
3. Edit SQL files.
4. Dry-run (optional) and Push: `./push.ps1`.

Local override example:

```json
{
  "credentialsFile": "C:/secure/path/google-credentials.json"
}
```

## Layout
```
<outputDir>/
  <project>/
    <dataset>/
      views/
        <view>.sql
      materialized_views/
        <mv>.sql
      routines/
        <routine>.sql
        <routine>.meta.json   # arguments, return type, language, routineType
```

## Notes
- Views and materialized views are stored as SQL only; we assume GoogleSQL (not legacy).
- Routines require a `.meta.json` sidecar to carry non-body attributes.
- Push protects production by default with a `-WhatIf` preview; pass `-Force` to apply.
- If `bq-sync.config.local.json` exists, it overrides matching top-level settings from `bq-sync.config.json`.

## HubSpot Survey Loads
- Use `load_hubspot_surveys.py` to create and upsert the monthly HubSpot survey exports into `pccw-internal-virt-agent-uat.GSO`.
- Default behavior scans `Temp/` for the latest matching SCN and Remedy survey workbooks.
- Loads are idempotent on `record_id`: rerunning the same export updates matching rows and inserts new ones.

Example:

```powershell
"g:/My Drive/Scripts/.venv/Scripts/python.exe" "g:/My Drive/Scripts/BigQuerySync/load_hubspot_surveys.py"
```
