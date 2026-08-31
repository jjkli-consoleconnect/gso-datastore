# Jira Close to Helix Duplication - Automation Blueprint

## Objective
- Trigger on Jira issue closure.
- Duplicate the closed Jira ticket into Helix.
- Replay Jira comments into Helix worklogs in original order.
- Close Helix ticket at the end when supported.
- Preserve original Jira timestamps as faithfully as API permits.

## Definitions
- Duplication run: one end-to-end processing of a single closed Jira issue.
- Phase model: CREATE -> WORKLOG_REPLAY -> CLOSE -> COMPLETE.
- Replay safety: rerun should not duplicate artifacts already synced.

## Status Snapshot
- Implemented in UAT: closed-event routing, live Jira issue fetch, Jira comment replay, idempotency phase checks, and Helix create payloads that preserve Jira source metadata in the description.
- Implemented in UAT and PROD: validated create notes pattern `category/item/type = Others` and safe dry-run validation that logs payloads without writes.
- Still validate before relying on them natively: Helix backdated `creationDate`, worklog `date`, worklog `author`, and terminal close transition behavior.

## Assumptions to validate early
- Jira automation trigger can send closure event with issue key.
- Helix status patch to terminal closed state is accepted in this tenant.
- Helix accepts current create notes pattern used in existing integration.
- Jira API account has permissions to read issue history and comments.

## End-to-end flow
1. Jira issue transitions to Closed/Done status.
2. Jira automation sends webhook to Cloud Function with issue key and transition metadata.
3. Function resolves canonical Jira issue snapshot from Jira API.
4. Function checks duplication idempotency table.
5. Function creates Helix ticket.
6. Function fetches full Jira comments and replays as Helix worklogs.
7. Function patches Helix status to Closed (or fallback path).
8. Function records completion and audit metadata in BigQuery.

## Trigger contract design
Minimal recommended webhook payload from Jira automation:
- issue.key
- issue.id (optional but useful)
- issue.fields.status.name
- issue.fields.resolutiondate
- webhookEvent and issue_event_type_name

Reasoning:
- Keep webhook small and deterministic.
- Fetch full source of truth directly via Jira API in function.

## Jira data acquisition plan
Required reads:
- GET issue details for:
  - summary
  - description
  - created
  - resolutiondate
  - customer/SR mapping fields (relatedEntity.customerId and relatedEntity.srId)
  - current status
- GET comments (paginated) for:
  - id
  - body
  - author
  - created
  - updated

Optional reads:
- Changelog for precise transition timestamp if resolutiondate quality is inconsistent.

## Helix create mapping plan
Create payload mapping:
- name <- Jira summary
- description <- Jira description plus source metadata block
- externalId <- Jira key
- priority <- default or mapped Jira priority
- ticketType <- Incident
- relatedEntity.customerId <- mapped from Jira fields
- relatedEntity.srId <- optional
- channel <- API/Customer
- notes <- create faultsymptom structure accepted in tenant

## Worklog replay plan
For each Jira comment in ascending created timestamp:
- Build patch note with @type=worklog.
- Include source metadata in text block:
  - Jira comment ID
  - author display name
  - original created timestamp
  - original updated timestamp
  - original body
- Send one PATCH per comment for clearer retries and error isolation.

Suggested worklog text template:
- Prefix line: Jira comment sync
- Metadata lines:
  - Source comment ID
  - Author
  - Created (Jira)
  - Updated (Jira)
- Blank line
- Body text

## Closure plan
Primary path:
- PATCH trouble ticket status to Closed.
- Verify by GET ticket and assert status.

Fallback paths:
- If Closed not allowed:
  - Try tenant-approved terminal status transition.
  - If business allows, use DELETE semantic to Cancelled (requires userKey).
  - Else mark run complete_with_limitations and write explicit alert.

## Timestamp retention strategy
### Target state requested
- Helix creation timestamp matches Jira created.
- Helix closure timestamp matches Jira closed timestamp.
- Helix worklog timestamps match Jira comment timestamps.

### Practical implementation approach
Layer 1 (always achievable):
- Persist exact Jira timestamps in BigQuery audit columns.
- Include exact Jira timestamps in worklog text.

Layer 2 (best effort via API fields):
- Attempt create with creationDate set to Jira created timestamp.
- Attempt patch worklog with note date if accepted.
- Attempt close timestamp carrying field only if endpoint supports it.

Validation gate:
- Perform create/patch/retrieve probes in UAT and compare round-trip timestamps.
- Promote only after deterministic acceptance is confirmed.

## Idempotency and replay model
Use a dedicated BigQuery table for duplication lifecycle.

Suggested table: jira_to_helix_close_dup_sync
Columns:
- jira_key STRING REQUIRED
- jira_issue_id STRING NULLABLE
- helix_id STRING NULLABLE
- phase STRING REQUIRED
- phase_key STRING REQUIRED
- source_created_ts TIMESTAMP NULLABLE
- source_closed_ts TIMESTAMP NULLABLE
- comment_id STRING NULLABLE
- comment_created_ts TIMESTAMP NULLABLE
- comment_updated_ts TIMESTAMP NULLABLE
- sync_status STRING REQUIRED
- error_message STRING NULLABLE
- correlation_id STRING REQUIRED
- created_timestamp TIMESTAMP REQUIRED

Phase keys:
- TICKET_CREATE
- COMMENT_REPLAY:{jira_comment_id}:{jira_comment_updated_or_created}
- TICKET_CLOSE

Rules:
- If TICKET_CREATE success exists, do not recreate Helix ticket.
- Replay only missing comment phase keys.
- If close phase already successful, short-circuit to complete.

## Error handling and retries
- Hard failures:
  - Missing Jira key
  - Missing customer mapping
  - Helix auth failure
  - Helix create rejection
- Soft failures:
  - Individual comment replay failures after ticket create
  - Close status failure after successful replay

Retry model:
- Webhook retries should be safe due to phase-key idempotency.
- Manual re-drive endpoint can reuse same flow with force flags.

## Logging and observability
Log context required in every line:
- correlation_id
- jira_key
- helix_id when available
- phase
- phase_key

Metrics to track:
- total runs
- create success rate
- comment replay count and failures
- close success rate
- average end-to-end latency

Alerting suggestions:
- create failed
- replay partial failed
- close failed
- completion with limitations

## Security and secrets
Secrets needed:
- Jira user email
- Jira API token
- Helix client ID
- Helix client secret
- Helix host name

Operational requirements:
- Keep function non-public if possible and enforce verification.
- If webhook must be public, validate source signature or shared secret header.
- Never log secrets or token payloads.

## UAT validation matrix before rollout
1. Trigger correctness:
- Closed event only, not create/comment events.
2. Create payload:
- mandatory fields accepted.
3. Timestamp probe:
- creationDate acceptance and retrieval equality check.
4. Comment replay:
- count and order match Jira.
5. Worklog date probe:
- whether note date is accepted and stored.
6. Close transition:
- status patch to Closed accepted and persisted.
7. Replay safety:
- duplicate webhook does not duplicate comments or re-close incorrectly.
8. Failure recovery:
- transient API failures recover cleanly on retry.

## Rollout plan
Phase 1: UAT dry-run mode
- Build payloads and log intended actions, no Helix mutations.

Phase 2: UAT live mode
- Enable create + replay + close for a controlled Jira issue subset.

Phase 3: Production pilot
- Feature flag by project key or label.
- Monitor error budget and rollback switch.

Phase 4: Full production
- Remove pilot filter after stability window.

## Concrete implementation tasks for current codebase
Target files:
- CloudFunctions/jira-to-helix/mss-to-remedy-create-uat/main.py
- CloudFunctions/jira-to-helix/mss-to-remedy-create-prod/main.py

Implementation status:
- Core create/comment/close flow is already present in the current UAT codebase.
- Prod now mirrors the same Jira source description formatting and can be dry-run validated safely.

Task list:
1. Add event guard for closed transition and route to duplication handler.
2. Add Jira fetch helpers for full issue and paginated comments.
3. Add lifecycle idempotency table and phase-key checks.
4. Add Helix create wrapper that can accept optional backdated creationDate.
5. Add worklog replay loop with deterministic text template and per-comment phase keys.
6. Add status close patch helper and verification readback.
7. Extend BigQuery writes for lifecycle/audit timestamps.
8. Add feature flags:
   - DUPLICATE_ON_CLOSE_ENABLED
   - ENABLE_HELIX_CLOSE_PATCH
   - ENABLE_HELIX_BACKDATE_FIELDS
9. Add robust response payload for operational visibility.
10. Update deploy/runbook docs for new trigger and rollback steps.

## Open questions requiring API owner confirmation
- Exact accepted field for setting creation timestamp at create time.
- Whether worklog note date/author are accepted in current route.
- Exact accepted close transition payload and allowed source states.
- Whether CLOSED and CANCELLED are both business-acceptable terminal states for this workflow.
- Whether userKey can be provisioned if delete-cancel fallback is needed.

## Confidence framing
- Workflow implementation confidence: high if close patch is supported in tenant.
- Perfect historical timestamp backfill in native Helix system fields: medium until UAT field-level probes confirm acceptance.
- Operational reliability confidence: high with phase-level idempotency and audit-led retries.
