# BigQuery Pull Playbook

## Auth
- `gcloud auth login`
- `gcloud auth application-default login`
- Fix auth before retry
- No blind reruns

## Repo Sync
- Use `BigQuerySync/pull.ps1` (Windows) or `BigQuerySync/pull_macos.sh` for repo-wide pull
- Pull mirrors BigQuery: orphan files and dataset folders are removed after a `bq show` confirmation
- `-DryRun` reports writes and deletions without changing anything
- `-Delta` skips unchanged objects using `BigQuerySync/.bq-sync.state.json`
- `-NoPrune` keeps local files that no longer exist in BigQuery

## Speed
- Listing is one region-level `INFORMATION_SCHEMA` query per project and location
- Region-level access denied → fall back to per-dataset queries, warning printed
- Failed listings are never pruned
- Empty definitions never clobber local files (re-fetched with `bq show`, else kept + error)

## Safety
- Never delete outside `<project>/BigQuery/<dataset>/{views,materialized_views,routines}`
- Non-managed folders (`tables/`, `scheduled_queries/`) are left alone
- Hidden datasets (folder names starting with `_`) are skipped

## Repo Hygiene
- `KnowledgeBase/` → guides, references
- `Temp/` → one-off scripts
- `shared/` → reusable utils
