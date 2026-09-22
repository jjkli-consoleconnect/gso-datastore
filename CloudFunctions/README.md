# Cloud Functions

Deployable functions are grouped by their current GCP project:

- `pccw-internal-virt-agent-uat/` - functions currently deployed to UAT
- `pccw-internal-virtual-agent/` - functions currently deployed to production
- `shared/` - project-neutral runtime modules copied into function source packages as needed
- `alerting/` - repository tooling, not a deployable Cloud Function

Each deployable function must remain in its own named subfolder. A function's folder records its deployment project, not every project it reads from or writes to. Cross-project data dependencies must be configured explicitly and removed as part of migration work.

When a function is migrated between projects, move its complete folder and update its deploy command, service account, secrets, triggers, schedules, BigQuery destinations, and documentation in the same change.
