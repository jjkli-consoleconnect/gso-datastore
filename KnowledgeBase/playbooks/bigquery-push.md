# BigQuery Push Playbook

## Auth
- `gcloud auth login`
- `gcloud auth application-default login`
- Fix auth before retry
- No blind reruns

## Repo Sync
- Use `BigQuerySync/push.ps1` for repo-wide sync
- `push.ps1 -Force` updates all SQL-backed objects
- One bad object stops full push

## Single View Deploy
- Read local `.sql`
- Run `CREATE OR REPLACE VIEW project.dataset.view AS <sql>`
- Use BigQuery Python client
- `location='europe'` for EU datasets
- Prefer direct DDL over `bq update --view`

## Validation
- Check only target object after deploy
- Do not run full push unless all objects ready

## Repo Hygiene
- `KnowledgeBase/` → guides, references
- `Temp/` → one-off scripts
- `shared/` → reusable utils
