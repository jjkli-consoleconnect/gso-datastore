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
