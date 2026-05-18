# Helix Trouble Ticket API UAT Runbook

Last updated: 2026-05-18
Scope: UAT tenant testing for auth, list, and create on internal Helix endpoint.

## 1) Final Outcome (Validated)

- Auth endpoint works.
- List endpoint works when `relatedEntity.customerId` is provided.
- Create endpoint works with the exact payload shape below.
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
