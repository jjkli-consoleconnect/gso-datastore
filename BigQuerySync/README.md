# BigQuery Sync (Pull/Push)

Minimal workflow to pull BigQuery objects (views, materialized views, routines) into versioned files and push changes back.

Pull mirrors BigQuery: objects that were deleted in BigQuery are removed locally too, and a full pull is fast because each project/location is listed with a single region-level query.

## Files
- `bq-sync.config.json` — configure projects/datasets, project-root output path, pull options.
- `pull.ps1` — export definitions from BigQuery to `outputDir` (Windows).
- `pull_macos.sh` — same pull for macOS/Linux.
- `push.ps1` — update BigQuery from local files.

## Prereqs
- gcloud SDK + `bq` CLI installed and authenticated.
- Permission to read and update datasets/views/routines.

## Authentication
- Default: use your current `gcloud` / Application Default Credentials session. For local setup, run `gcloud auth login` and, if you also use Python Google client libraries, `gcloud auth application-default login`.
- Optional local override: create `BigQuerySync/bq-sync.config.local.json` and put `credentialsFile` there if you absolutely need a key file. Keep that file outside git.
- Do not store credential JSON files in this repo.

## Quick start
1. Edit `bq-sync.config.json` (projects, datasets, outputDir, resourceSubdir, location).
2. Pull: use VS Code task `BigQuery: Pull`, `BigQuery: Pull (Delta)` or `BigQuery: Pull (DryRun)`.
3. Edit SQL files.
4. Dry-run (optional) and Push: `./push.ps1`.

## Pull behaviour

### Mirror (default)
- Managed objects are rewritten from BigQuery into `views/`, `materialized_views/` and `routines/`.
- Local files whose object no longer exists in BigQuery are deleted, and dataset folders that no
  longer exist in BigQuery are removed when they only contain managed files.
- Folders that still hold other files (for example `tables/`, `scheduled_queries/`) are left in
  place with a warning, and hidden datasets (folder names starting with `_`) are skipped.
- Every deletion is confirmed with a single `bq show` first, so an object that is merely hidden
  from the metadata listing (IAM, naming) is never deleted.
- A listing that failed is never pruned, so a transient BigQuery error cannot wipe local files.
- A row with an empty definition (metadata glitches happen) never overwrites a good local file: the pull
  re-fetches it with `bq show`, and otherwise keeps the file untouched and reports it as an error.

### Delta
- `-Delta` (or `"delta": true`) skips writing objects whose fingerprint is unchanged, and skips the
  per-routine `bq show` when `last_altered` has not changed.
- Fingerprints live in `BigQuerySync/.bq-sync.state.json` (git-ignored, rewritten on each pull).
- Delta trusts an existing local file, so local edits survive; run a normal pull to force every file
  back to the BigQuery definition.

### Options

| Pull flag | Config key | Default | Effect |
| --- | --- | --- | --- |
| `-NoPrune` | `prune: false` | prune on | never delete local files |
| `-SkipVerifyRemovals` | `verifyRemovals: false` | verify on | delete without the `bq show` confirmation |
| `-Delta` | `delta: true` | off | only write objects that changed |
| `-DryRun` | – | off | report writes and deletions, change nothing |

macOS equivalents: `./pull_macos.sh <config> [--delta] [--dry-run] [--no-prune] [--skip-verify-removals]`.

### Why it is quick
Listing uses one region-level query per project and location
(`SELECT ... FROM \`project\`.\`region-EU\`.INFORMATION_SCHEMA.VIEWS`) instead of one `bq show`
plus three listing queries per dataset. If a region-level query is not permitted for your
account, pull falls back to per-dataset queries for that location and warns about it.

## Layout
```
<repository>/
  <project-id>/
    BigQuery/
      <dataset>/
        views/
          <view>.sql
        materialized_views/
          <mv>.sql
        routines/
          <routine>.sql
          <routine>.meta.json   # arguments, return type, language, routineType
```

With the checked-in config, pulls write to:

- `pccw-internal-virt-agent-uat/BigQuery/<dataset>/`
- `pccw-internal-virtual-agent/BigQuery/<dataset>/`

## Notes
- Views and materialized views are stored as SQL only; we assume GoogleSQL (not legacy).
- Routines require a `.meta.json` sidecar to carry non-body attributes.
- Push protects production by default with a `-WhatIf` preview; pass `-Force` to apply.
- If `bq-sync.config.local.json` exists, it overrides matching top-level settings from `bq-sync.config.json`.
- Pull before a big push: a file that no longer exists in BigQuery would otherwise be recreated by push.

## HubSpot Survey Loads
- Use `load_hubspot_surveys.py` to create and upsert the monthly HubSpot survey exports into `pccw-internal-virt-agent-uat.GSO`.
- Default behavior scans `Temp/` for the latest matching SCN and Remedy survey workbooks.
- Loads are idempotent on `record_id`: rerunning the same export updates matching rows and inserts new ones.

Example:

```powershell
"g:/My Drive/Scripts/.venv/Scripts/python.exe" "g:/My Drive/Scripts/BigQuerySync/load_hubspot_surveys.py"
```
