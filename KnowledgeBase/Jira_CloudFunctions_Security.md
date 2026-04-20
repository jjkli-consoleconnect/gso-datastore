# Jira Cloud Functions Security Baseline

Last updated: 2026-04-17

## Scope

Prod Jira functions in `pccw-internal-virtual-agent`:

- `jira-tickets-sync`
- `jira-comments-sync`
- `jira-changelogs-sync`
- `jira-tickets-nightly`
- `jira-comments-nightly`
- `jira-changelogs-nightly`

## Required Security State

### 1. No anonymous invoke

All Jira functions must reject unauthenticated external requests.

Required behavior:

- Cloud Run / Gen2 service must **not** grant `roles/run.invoker` to `allUsers`
- unauthenticated probe to each `*.run.app` URL should return `403`

### 2. Dedicated service accounts only

Do **not** use the default compute service account for Jira functions or schedulers.

Use these identities:

- Runtime SA: `jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com`
- Scheduler SA: `jira-scheduler-invoker@pccw-internal-virtual-agent.iam.gserviceaccount.com`

### 3. Scheduler auth pattern

All Jira scheduler jobs must use OIDC with the scheduler SA.

Expected pattern:

- scheduler job has `httpTarget.oidcToken.serviceAccountEmail = jira-scheduler-invoker@pccw-internal-virtual-agent.iam.gserviceaccount.com`
- target service grants `roles/run.invoker` only to that scheduler SA

### 4. Runtime permissions

Runtime SA should stay minimal.

Current intended access:

- Prod project `pccw-internal-virtual-agent`
  - no broad project-level roles
  - secret-level `roles/secretmanager.secretAccessor` only for Jira secrets
- UAT project `pccw-internal-virt-agent-uat`
  - `roles/bigquery.jobUser`
  - `roles/bigquery.dataEditor`

Reason:

- code reads secrets from prod Secret Manager
- code writes Jira data into UAT BigQuery

### 5. Deployment defaults

All prod Jira deploy scripts must preserve:

- `--no-allow-unauthenticated`
- runtime service account = `jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com`

Do not change back to:

- `--allow-unauthenticated`
- `370161436243-compute@developer.gserviceaccount.com`

## Dependency Baseline

Nightly Jira functions were updated after dependency audit.

Important pin:

- `requests==2.33.0`

Do not downgrade to `2.32.3`.

## Verification Checklist

Run after any Jira function deploy or IAM change:

1. Verify runtime SA:
   - `gcloud functions describe <function> --project=pccw-internal-virtual-agent --region=europe-west2 --format="value(serviceConfig.serviceAccountEmail)"`
2. Verify invoker policy:
   - `gcloud run services get-iam-policy <service> --project=pccw-internal-virtual-agent --region=europe-west2`
3. Verify anonymous access blocked:
   - `curl -I https://<service-url>` should return `403`
4. Verify scheduler OIDC identity:
   - `gcloud scheduler jobs describe <job> --project=pccw-internal-virtual-agent --location=europe-west2`
5. Verify Python deps:
   - `python -m pip_audit -r <requirements.txt>`

## Important Caveat

Current ingress is still `ALLOW_ALL`.

That means:

- endpoints remain internet-routable
- but authenticated invoke is required

If future security policy requires true internal-only exposure, redesign trigger path away from direct public HTTPS endpoints.