# BigQuery Sync (Pull/Push)

Minimal workflow to pull BigQuery objects (views, materialized views, routines) into versioned files and push changes back.

## Files
- `bq-sync.config.json` — configure projects/datasets, output path, and options.
- `pull.ps1` — export definitions from BigQuery to `outputDir`.
- `push.ps1` — update BigQuery from local files.

## Prereqs
- gcloud SDK + `bq` CLI installed and authenticated.
- Permission to read and update datasets/views/routines.

## Quick start
1. Edit `bq-sync.config.json` (projects, datasets, outputDir, location, credentialsFile if needed).
2. Pull: use VS Code task `BigQuery: Pull` or run `./pull.ps1`.
3. Edit SQL files.
4. Dry-run (optional) and Push: `./push.ps1`.

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
