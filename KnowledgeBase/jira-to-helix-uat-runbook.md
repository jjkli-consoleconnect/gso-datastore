# Helix Trouble Ticket API UAT Runbook

Last updated: 2026-05-19
Scope: UAT tenant testing for auth, list, and create on internal Helix endpoint.

## 1) Final Outcome (Validated)

- Auth endpoint works.
- List endpoint works when `relatedEntity.customerId` is provided.
- Create endpoint works with the exact payload shape below.
- Current Jira-to-Helix function reads Helix `customerId` directly from Jira MSS field `customfield_11247` (`MSS customer`).
- New ticket was created and returned by API:
  - `INC000006741116`

## 2) Endpoints and Headers

- Auth URL:
  - `https://auth.stage.consoleconnect.com/oauth/token`
- API Base URL:
  - `https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix`
- Create endpoint:
  - `POST /troubleTicket`
- List endpoint:
  - `GET /troubleTicket?mode=Detail&relatedEntity.customerId=<VALUE>&limit=<N>`

Required headers for API calls:
- `Authorization: Bearer <token>`
- `X-System-Id: jira`
- `Content-Type: application/json` (POST only)

## 3) Known Working Values from UAT

These were validated during manual API testing and are examples, not a lookup source for the current function.

- `customerId`: `TES037`
- `serviceId`: `S0000001`
- Notes values accepted in successful flow:
  - `category = Others`
  - `item = Others`
  - `type = Others`

## 4) Critical Payload Rules (Most Important)

1. Root field `@type` must be exactly `troubleTicket`.
2. For stable create behavior, use notes array with all 3 entries:
   - `id: category`, `@type: faultsymptom`, `text: Others`
   - `id: item`, `@type: faultsymptom`, `text: Others`
   - `id: type`, `@type: faultsymptom`, `text: Others`
3. `relatedEntity` should include customer profile shape used by existing tickets:
   - `name: TES037`
   - `role: customerId`
   - `@type: RelatedEntity`
   - `@referredType: Profile`
4. Use `curl.exe` and payload from file (`-d @file`) to avoid PowerShell escaping issues.

## 5) Error Map and Root Cause

- Error: `Malformed JSON request`
  - Cause: inline JSON escaping/interpolation issues in PowerShell.
  - Fix: write JSON to file and send with `-d "@path"`.

- Error: `Required String parameter 'relatedEntity.customerId' is not present`
  - Cause: list request missing query parameter.
  - Fix: include `relatedEntity.customerId=<customerId>` in query string.

- Error: `[Invalid Trouble Ticket @type]`
  - Cause: incorrect root `@type` value.
  - Fix: set root `@type` to exactly `troubleTicket`.

- Error: `[troubleTicket - notes - item]`
  - Cause: notes structure/value mismatch.
  - Fix: use the 3-note pattern (`category`, `item`, `type`) with `faultsymptom` and `Others`.

## 6) Working Create Payload (Reference)

```json
{
  "@type": "troubleTicket",
  "name": "API Incident TES037 <timestamp>",
  "description": "API integration test - TES037/S0000001",
  "priority": "Low",
  "ticketType": "Incident",
  "relatedEntity": [
    {
      "name": "TES037",
      "role": "customerId",
      "@type": "RelatedEntity",
      "@referredType": "Profile"
    },
    {
      "name": "S0000001",
      "role": "serviceId",
      "@type": "RelatedEntity",
      "@referredType": "Service"
    }
  ],
  "channel": {
    "name": "Phone",
    "@type": "Internal"
  },
  "notes": [
    {
      "id": "category",
      "text": "Others",
      "@type": "faultsymptom"
    },
    {
      "id": "item",
      "text": "Others",
      "@type": "faultsymptom"
    },
    {
      "id": "type",
      "text": "Others",
      "@type": "faultsymptom"
    }
  ],
  "relatedParty": [
    {
      "name": "Adonis Lee Villamor",
      "phone": "+639171234567",
      "email": "avillamor@consoleconnect.com"
    }
  ]
}
```

## 7) Minimal Test Flow (Copy/Paste)

```powershell
# 1) Get token
$t = curl.exe -s -k -X POST "https://auth.stage.consoleconnect.com/oauth/token" `
  -d "client_id=<CLIENT_ID>" `
  -d "client_secret=<CLIENT_SECRET>" `
  -d "grant_type=client_credentials" `
  -d "audience=api.stage.corp.consoleconnect.com"
$token = ($t | ConvertFrom-Json).access_token

# 2) List existing tickets (required customerId)
curl.exe -s -k `
  -H "Authorization: Bearer $token" `
  -H "X-System-Id: jira" `
  "https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket?mode=Detail&relatedEntity.customerId=TES037&limit=5"

# 3) Create ticket using file payload
# Save working JSON into $env:TEMP\helix_create.json first
curl.exe -s -k -X POST `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -H "X-System-Id: jira" `
  -d "@$env:TEMP\helix_create.json" `
  "https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket"
```

## 8) Security Notes

- Do not store real `client_secret` in repo files.
- Use environment variables or secret manager for credentials.
- Keep this document as process and payload reference only.

## 9) Quick Troubleshooting Checklist

- Token acquired and not expired.
- API path includes `/cs-helix-ticketing/internalHelix`.
- Header `X-System-Id: jira` present.
- Root `@type` is `troubleTicket`.
- List query includes `relatedEntity.customerId`.
- POST body sent from file, not fragile inline escaped JSON.
- Notes array uses `category/item/type` with `faultsymptom` and accepted values.

## 10) Cloud Function Integration Findings (2026-05-19)

These findings are specific to deploying Jira-to-Helix from Cloud Functions in UAT over VPC.

### A) OAuth audience must be exact (no scheme)

- Working value:
  - `api.stage.corp.consoleconnect.com`
- Non-working values:
  - `https://api.stage.corp.consoleconnect.com`
  - `https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix`

### B) Cloud Function network path must match UAT webhook pattern

- Region: `europe-west2`
- VPC connector: `eu-uat-wanda-vpc-conn`
- Egress: `ALL_TRAFFIC`
- Runtime service account should align with working UAT webhook functions.

### C) Internal host routing behavior

- `jira-to-helix-uat-host-name` currently resolves to private IP `10.15.0.3`.
- Helix cert does not match raw private IP hostname validation.
- For private IP route, preserve:
  - URL target via host from `jira-to-helix-uat-host-name`
  - HTTP `Host` header as `api.stage.corp.consoleconnect.com`
- If TLS hostname mismatch appears (`certificate verify failed: IP address mismatch`), route/SSL handling must account for this internal IP path.

### D) Create vs list request differences

- List requires query parameter:
  - `relatedEntity.customerId=<customerId>`
- Create should post directly to `/troubleTicket` with payload body and must not depend on list-only query parameters.

### E) Known good end-to-end synthetic result

- Cloud Function synthetic webhook test created Helix incident:
  - `INC000006741118`
- BigQuery idempotency row recorded `success` for synthetic key.
- Jira backlink update can fail with `404` for synthetic/non-existent Jira keys; this is expected in synthetic tests.

### F) Secret hygiene for UAT Helix credentials

- Store credentials in Secret Manager only (no plaintext in repo).
- Keep only one enabled version for:
  - `jira-to-helix-uat-helix-auth0-client-id`
  - `jira-to-helix-uat-helix-auth0-client-secret`

## 11) Jira Comment -> Helix Worklog Sync (Execution Guide)

This section is the authoritative guide for syncing Jira comments to Helix worklogs in UAT.

### 11.1 Objective and Scope

- Trigger on Jira comment create and comment edit events.
- Add one Helix worklog note per Jira comment version.
- Worklog type in Helix must be `JIRA Work Log`.
- Integration owner prefix convention: use `jira-to-helix` for all new GCP resources.

### 11.2 Function and Runtime Contract

- Cloud Function:
  - `mss-to-remedy-create-uat`
- Trigger URL:
  - `https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/mss-to-remedy-create-uat`
- Region / network:
  - `europe-west2`, VPC connector `eu-uat-wanda-vpc-conn`, egress `ALL_TRAFFIC`
- Auth header toward Helix:
  - `Authorization: Bearer <token>`
  - `X-System-Id: jira`

### 11.3 Jira Automation Rules Required

Create two Jira Automation rules, both posting to the same URL:

The same endpoint handles issue-created and comment-edited payloads. The function inspects the webhook contents and routes create, comment replay, and close-triggered duplication internally.

1. Rule A
   - Trigger: `Issue commented`
   - Condition: project filter (for example `MSS`)
   - Action: `Send web request`

2. Rule B
   - Trigger: `Comment edited`
   - Condition: same project filter
   - Action: `Send web request`

Both rules must use:

- Method: `POST`
- Header: `Content-Type: application/json`

### 11.4 Jira Web Request Payload (Recommended)

Use this payload template:

```json
{
  "issue": {
    "key": "{{issue.key}}"
  },
  "comment": {
    "id": "{{comment.id}}",
    "created": "{{comment.created}}",
    "updated": "{{comment.updated}}",
    "body": "{{comment.body}}",
    "author": {
      "displayName": "{{comment.author.displayName}}",
      "accountId": "{{comment.author.accountId}}"
    }
  }
}
```

Notes:

- Jira can emit invalid JSON when comment body contains line breaks. The function includes a loose-parser fallback to recover required fields from raw payload text.
- If Jira renders valid JSON reliably in your tenant, this also works for `body`:
  - `"body": {{comment.body.jsonEncode}}`

### 11.5 Required Jira->Helix Mapping Prerequisite

For comment sync to work, the Jira issue must already contain the mapped Helix ticket ID in one of these fields:

- `customfield_10647`
- `customfield_14905`
- `customfield_10161`
- `customfield_15154`

Current create flow also backfills the first writable field from the same candidate list after Helix create succeeds. In the current sandbox, `customfield_14905` was writable when `customfield_10647` returned 400.

If none exists, comment sync fails with:

- `No Remedy ticket number found on Jira issue`

### 11.6 Helix PATCH Payload That Works

The working PATCH contract for this tenant is:

```json
{
  "@type": "troubleTicket",
  "notes": [
    {
      "id": "JIRA Work Log",
      "text": "Jens Li said:\n\nwhat if i reply to the customer?",
      "@type": "worklog"
    }
  ]
}
```

Critical rules:

1. Root `@type` is mandatory for PATCH (`troubleTicket`).
2. Notes entry for worklog uses:
   - `id = JIRA Work Log`
   - `@type = worklog`
   - `text = message`
3. Do not add custom/extra fields to worklog PATCH body unless revalidated.

### 11.7 Known Non-Working Fields in This Flow

In this UAT API route, adding note fields like `date` and custom `author` in PATCH requests led to API 400 errors in tests.

Observed error patterns:

- `[Invalid Trouble Ticket @type]` when root `@type` omitted.
- `Malformed JSON request` for unsupported note field combinations.

### 11.8 Display Format Implemented for Readability

Current generated worklog text:

- New comment:
  - `Jens Li said:`
  - blank line
  - `<comment body>`
- Edited comment:
  - `Jens Li said (edited):`
  - blank line
  - `<comment body>`

### 11.9 Idempotency and Edit Behavior

- Ticket create idempotency table:
  - `Testing.jira_to_helix_sync`
- Comment sync idempotency table:
  - `Testing.jira_to_helix_comment_sync`
- Comment idempotency key:
  - `<comment_id>:<effective_timestamp>`
  - effective timestamp prefers `updated`, fallback to `created`

Result:

- Retries for same comment version are deduped.
- Edits of existing comment IDs are treated as new versions and synced.

### 11.10 API Verification Commands (Direct)

Token:

```powershell
$t = curl.exe -s -k -X POST "https://auth.stage.consoleconnect.com/oauth/token" `
  -d "client_id=<CLIENT_ID>" `
  -d "client_secret=<CLIENT_SECRET>" `
  -d "grant_type=client_credentials" `
  -d "audience=api.stage.corp.consoleconnect.com"
$token = ($t | ConvertFrom-Json).access_token
```

Patch one ticket worklog using file payload:

```powershell
$ticketId = "INC000006741120"
$payload = @'
{
  "@type": "troubleTicket",
  "notes": [
    {
      "id": "JIRA Work Log",
      "text": "api test message",
      "@type": "worklog"
    }
  ]
}
'@

$payload | Out-File "$env:TEMP\helix_patch_worklog.json" -Encoding utf8 -NoNewline

curl.exe -s -k -X PATCH `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -H "X-System-Id: jira" `
  -d "@$env:TEMP\helix_patch_worklog.json" `
  "https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/$ticketId"
```

Get ticket and inspect latest notes:

```powershell
$g = curl.exe -s -k `
  -H "Authorization: Bearer $token" `
  -H "X-System-Id: jira" `
  "https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket/$ticketId"

$obj = $g | ConvertFrom-Json
$obj.notes | Select-Object -Last 5 | ConvertTo-Json -Depth 6
```

### 11.11 Fast Failure Triage

If Jira Automation fails with 400 `Invalid JSON payload`:

1. Check if comment had multiline content.
2. Confirm payload body mapping for `comment.body` in automation.
3. Re-run and inspect function logs for raw payload snippet.

If Jira Automation fails with 500 and Helix 400:

1. Check function logs for Helix response body.
2. Verify root `@type` exists in PATCH payload.
3. Ensure note shape is exactly `id/text/@type`.

If no worklog is posted and function says no ticket number:

1. Confirm Jira issue contains Helix ID in one of mapped custom fields.
2. Re-open ticket-create mapping or backlink update logic.

## 12) Support Group Routing Findings (ASOC vs HKNOC)

### 12.1 What We Proved Today

- `relatedParty` in this Helix API is contact information, not support-group assignment.
- Putting `ASOC` into `relatedParty` shows `ASOC` in Contact Name, which is wrong for this use case.
- Top-level `assignedGroup`, `supportGroup`, and `relatedEntity` role values like `Assigned Group` are accepted or silently ignored by the API, but they do not change the Support Group shown in the UI.
- The Support Group continues to resolve to `HKNOC` unless Helix routing/server-side config changes.

### 12.2 Why the Earlier Theory Was Wrong

- The spec section for create/update says `relatedParty` is the contact person structure.
- The patch contract explicitly says `relatedParty` is only allowed when role is `Contact`.
- Our earlier attempt to force `ASOC` through `relatedParty` was the reason `ASOC` appeared in Contact Name.

### 12.3 Empirical Dummy Tickets Created Today

- `INC000006741124` - tested top-level `assignedGroup = ASOC`
- `INC000006741125` - tested top-level `supportGroup = ASOC`
- `INC000006741126` - tested `relatedEntity` role `Assigned Group`
- `INC000006741127` - tested `relatedParty` role `Assigned Group`
- `INC000006741128` - tested clean create with `assignedGroup` only
- `INC000006741129` - full-field probe with create, retrieve, list, and patch

### 12.4 Final Mapping Result

| Field tested | Observed result |
| --- | --- |
| `relatedParty.name = ASOC` | Populates Contact Name, not Support Group |
| `assignedGroup = ASOC` | Ignored by API response / does not change UI Support Group |
| `supportGroup = ASOC` | Ignored by API response / does not change UI Support Group |
| `relatedEntity.role = Assigned Group` | Ignored by API response / no visible assignment change |
| PATCH with same fields | Does not move Support Group away from `HKNOC` |

### 12.5 Operational Conclusion

- The Jira-to-Helix integration should **not** try to set Support Group via `relatedParty`.
- The current create/patch contract does **not** expose a writable Support Group field that we can verify from the API.
- If business requires `ASOC` instead of `HKNOC`, the fix is likely Helix-side routing / assignment rules, or an undocumented field/endpoint from the API owner.

### 12.6 Code Notes

- File: `pccw-internal-virt-agent-uat/CloudFunctions/mss-to-remedy-create-uat/main.py`
- Keep `relatedParty` reserved for actual contact info only.
- Do not reintroduce `relatedParty` with `role = "Assigned Group"`.
- Any future support-group change should be validated against Helix UI with a fresh dummy create before deploying.

### 12.7 Deployment Record

- Function: `mss-to-remedy-create-uat`
- Region: `europe-west2`
- Current validated revision: `mss-to-remedy-create-uat-00026-qug`
- Date of findings: `2026-08-07`

### 12.8 Scope Note

- Existing tickets already created under `HKNOC` require Helix-side reassignment if business wants `ASOC`.
- For future changes, use the dummy tickets above as the evidence set before altering payload mapping again.

