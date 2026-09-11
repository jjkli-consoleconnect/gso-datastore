# Linxa Connect API Integration Guide

Detailed instructions for an AI agent or engineer connecting to the Linxa Connect API and retrieving CDR data.

This document is an integration guide, not a credential store. Never put a real password, API key, JWT, refresh token, or bearer token in source code, chat messages, committed files, logs, or command history.

## 1. API identity and network

Base URL:

```text
https://pccwg.linxa.com/api/connect
```

The hostname currently resolves to a private RFC1918 address (`172.27.12.11`) from the company network. The API is reachable over HTTPS/TCP 443 from the workstation, but a public cloud runtime may not have a route to it.

For a Google Cloud Function, use the existing Jira Cloud Function VPC pattern:

- Cloud Functions Gen2.
- Region `europe-west2`.
- UAT connector: `projects/pccw-internal-virt-agent-uat/locations/europe-west2/connectors/eu-uat-wanda-vpc-conn`.
- Production connector: `projects/pccw-internal-virtual-agent/locations/europe-west2/connectors/eu-prod-wanda-vpc-conn`.
- Use `--egress-settings all` when all outbound traffic must route through the VPC.
- Use a dedicated runtime service account.
- Store Linxa credentials in Secret Manager.

See [VPC_UAT.md](VPC_UAT.md) and [Linxa_CDR_Datapipe_Architecture.md](Linxa_CDR_Datapipe_Architecture.md).

## 2. Authentication

The documented login endpoint is:

```http
POST /auth/v1/validate-credential
Content-Type: application/json
Accept: application/json
```

Request:

```json
{
  "username": "<LINXA_USERNAME>",
  "password": "<LINXA_PASSWORD>"
}
```

The response is expected to contain a session token. Different API documentation revisions name the field differently (`accessToken` or `token`), so inspect the response property names without printing the token value. Also capture `tokenType`, `expiresIn`, and any refresh-token field if supplied.

PowerShell login pattern:

```powershell
$baseUrl = 'https://pccwg.linxa.com/api/connect'
$username = $env:LINXA_USERNAME
$password = $env:LINXA_PASSWORD

$authResponse = Invoke-RestMethod `
  -Method Post `
  -Uri "$baseUrl/auth/v1/validate-credential" `
  -ContentType 'application/json' `
  -Body (@{
    username = $username
    password = $password
  } | ConvertTo-Json -Compress)

# Inspect names only. Never print the token.
$authResponse.PSObject.Properties.Name

$token = if ($authResponse.accessToken) {
  $authResponse.accessToken
} else {
  $authResponse.token
}

if ([string]::IsNullOrWhiteSpace($token)) {
  throw 'Linxa authentication succeeded without a usable token field.'
}
```

For existing integrations that already have a valid credential string, the tested CDR calls used it in the `Authorization` header. Preserve the exact format supplied by Linxa. Some environments use a raw credential value such as `1:<credential>`; others use a JWT with the `Bearer ` prefix. Do not guess between formats when a login token is available.

Authenticated request header pattern:

```powershell
$headers = @{
  Authorization = "Bearer $token"
  Accept = 'application/json'
  'User-Agent' = 'consoleconnect-linxa-client/1.0'
}
```

If Linxa supplies a raw authorization value rather than a JWT, use that value exactly:

```powershell
$headers = @{
  Authorization = $env:LINXA_AUTHORIZATION
  Accept = 'application/json'
}
```

Do not send API keys, passwords, or tokens in the JSON body unless Linxa explicitly documents that format for the endpoint.

## 3. First safe connectivity test

Use a small, read-only CDR request. Set `showMasked` to `true` and request one row.

```powershell
$payload = @{
  presetId = '284'
  serviceType = 'V'
  showMasked = $true
  filters = @{
    from = '2026-09-10 07:00'
    to = '2026-09-10 09:30'
  }
  range = @{
    start = 0
    length = 1
  }
} | ConvertTo-Json -Compress -Depth 5

$response = Invoke-WebRequest `
  -UseBasicParsing `
  -Method Post `
  -Uri "$baseUrl/v1/cdr-archive/getSummaryReport" `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $payload

$response.StatusCode
$response.Content
```

Expected success is HTTP `200` with a JSON array. The first array element is the column header row. Remaining elements are CDR rows.

## 4. CDR Summary request

Endpoint:

```http
POST /v1/cdr-archive/getSummaryReport
```

Verified request shape:

```json
{
  "presetId": "284",
  "serviceType": "V",
  "showMasked": true,
  "filters": {
    "from": "2026-09-10 07:00",
    "to": "2026-09-10 09:30"
  },
  "range": {
    "start": 0,
    "length": 1000
  }
}
```

Important details:

- `presetId` is tenant-specific. Swagger's `1001` is only an example and returned `Preset does not exists` for this tenant.
- Preset `264` returned HTTP `200` in testing.
- Preset `284` returned HTTP `200` in testing and is the preferred analysis preset currently documented here.
- `serviceType` value `V` was accepted for voice traffic.
- CDR filter timestamps were accepted as `YYYY-MM-DD HH:mm` strings.
- `showMasked: true` should be the default for testing, development, and reports that do not need telephone numbers.
- The API response is an array, not a normal `{ data: [...] }` wrapper.

## 5. Confirmed preset 284 columns

Preset `284` returned 33 columns in this order during testing:

```text
Session Start
Call Start
Finish
A Number (From)
A Number
A Number (Pai)
A Number (Diversion)
B Number
Duration (sec)
Duration (min)
Origin
Original Origin
Destination
Original Destination
CDR ID
Incoming Carrier
Outgoing Carrier
Traffic Format
Incoming Trunk
Outgoing Trunk
A Number Prefix
B Number Prefix
Status Code
Sip Response Code
System Duration
PDD
Ring Duration
Routing Decision Prefix
Last Hunt
Translation Result Types
External Lookup Result
Incoming Carrier ID
Outgoing Carrier ID
```

The exact column set is controlled by the Linxa preset. Always use the returned header row rather than hard-coding the order.

## 6. Parsing the array response safely

PowerShell can enumerate a JSON array unexpectedly. Keep the parsed array wrapped when iterating rows:

```powershell
$parsed = ConvertFrom-Json -InputObject $response.Content
$header = @($parsed[0])

$rows = for ($index = 1; $index -lt $parsed.Count; $index++) {
  ,@($parsed[$index])
}

$columnIndex = @{}
for ($index = 0; $index -lt $header.Count; $index++) {
  $columnIndex[[string]$header[$index]] = $index
}

foreach ($row in $rows) {
  $cdrId = $row[$columnIndex['CDR ID']]
  $durationSeconds = $row[$columnIndex['Duration (sec)']]
  # Transform into a typed object before loading into BigQuery.
}
```

Do not log full rows. At most, log status code, number of rows, response bytes, window, and elapsed time.

## 7. Pagination and daily extraction

The API uses offset-style pagination:

```json
{
  "range": {
    "start": 0,
    "length": 1000
  }
}
```

For the next page, increase `start` by the number of data rows returned. Row zero is the header and must not be counted as data.

Recommended algorithm:

1. Choose a closed time window, such as the previous complete day.
2. Split the day into hourly or 30-minute windows.
3. Request each window with `start=0` and `length=1000`.
4. Read the header from the first response.
5. Continue paging while the response contains 1000 data rows.
6. Stop when a page contains fewer than 1000 data rows.
7. Deduplicate by `CDR ID`.
8. Record the window, page offset, row count, and API status in run metadata.

Do not rely on one huge full-day request with very deep offsets. Testing showed that offsets around `10000` can be slow, and deeper sparse probes returned `403`. Smaller time windows reduce timeout risk and make retries safer.

Approximate observed volume:

- One 1,000-row response was about 0.43 MB of JSON.
- A full day had at least 10,000 rows in the test window.
- This is a manageable BigQuery volume, but API request count and retry behavior matter more than storage cost.

## 8. CDR data and IDD classification

Preset `284` does not expose an obvious `IDD`, `001`, or `0060` flag in the tested fields. A 1,000-row sample had zero direct matches in:

- `Traffic Format`
- `Origin`
- `Destination`
- `A Number Prefix`
- `B Number Prefix`
- `Routing Decision Prefix`
- Carrier and trunk fields
- Masked A/B number values

The data can support a broad origin/destination classification. For example, Hong Kong-to-Hong Kong can be separated from Hong Kong-to-non-Hong-Kong. That is not proof of access-code classification. `001/0060` may be represented in a Linxa routing/product configuration, a different preset, or an external service mapping.

Do not label a call as IDD solely because the origin and destination countries differ unless the business definition explicitly approves that rule.

## 9. Other API areas

The API documentation lists these read/query areas:

```text
POST /v1/carriers/get
POST /v1/carrier-overview/get
POST /v1/routing-tree/get
POST /v1/routing-test
POST /v1/percentage-routing/get
POST /v1/granular-routing/get
POST /v1/exceptional-routing/get
POST /v1/blockings/get
POST /v1/blacklist/get
POST /v1/whitelist/get
POST /v1/unknownNumbers/get
POST /v1/report-builder/getReport
POST /v1/cdr-archive/getSummaryReport
POST /v1/cdr-archive/getRatedReport
GET  /v1/log/get
POST /v1/log/get
GET  /v1/user/session-log/get
POST /v1/user/session-log/get
```

Access is permission-specific. In testing, the stored authorization reached the CDR Summary endpoint, while carrier overview, routing tree, and system log calls returned `403 insufficient privileges`. Do not infer that access to CDR implies access to every API area.

## 10. Error interpretation

Common observed responses:

| HTTP | Application code | Meaning |
|---:|---:|---|
| 200 | N/A | Request accepted; inspect array response. |
| 400 | `500001` | Request validation or tenant configuration error. Examples: missing `serviceType`, missing `presetId`, invalid preset. |
| 401 | `401006` | Authorization header missing. |
| 401 | `401001` | API key or authorization value invalid. |
| 401 | `401003` | Login credentials invalid. |
| 403 | `403002` | Authenticated but insufficient endpoint privilege, or gateway policy denial. |
| 405 | N/A | HTTP method not allowed, such as GET against a POST-only report endpoint. |

For an error, record only HTTP status, application response code, message, endpoint name, and request window. Never record authorization headers or request credentials.

## 11. Proposed Cloud Function datapipe

No implementation is included in this document. A future implementation should follow the existing Jira pipes:

```text
Cloud Scheduler
    -> authenticated HTTP Cloud Function Gen2
        -> Serverless VPC Access connector
            -> private Linxa API over HTTPS
        -> Secret Manager for credentials
        -> BigQuery staging table
        -> BigQuery MERGE into final partitioned table
        -> PipelineRuns operational logging
```

Suggested runtime behavior:

- Use a dedicated function folder under `CloudFunctions/`.
- Put reusable helpers under `CloudFunctions/shared/`.
- Use the repo's `setup_root_logging` and `PipelineRuns` logging pattern.
- Use the previous complete day as the normal extraction window.
- Add a small overlap window if Linxa records can arrive late.
- Deduplicate by `CDR ID`.
- Partition BigQuery by call date/time.
- Keep raw API response rows out of logs.
- Retry transient HTTP failures with bounded exponential backoff.
- Treat `400` preset/schema errors as configuration failures, not retryable network failures.
- Treat `401` as a secret/token problem and `403` as an access/network-policy problem until proven otherwise.
- Make the function idempotent so a failed run can be safely repeated.

## 12. Security requirements

- Rotate any credential that has appeared in a repository file, terminal command, chat message, screenshot, or log.
- Remove plaintext secrets from `KnowledgeBase/LinxaAPI.md` and any other tracked file before committing.
- Use Secret Manager in deployed environments.
- Mask numbers unless a documented business requirement needs unmasked data.
- Restrict function invocation with IAM; do not use unauthenticated invocation for production syncs.
- Do not put JWTs in query strings.
- Do not print request headers or complete API responses.
- Limit report windows and page sizes during testing.
- Confirm data retention and access controls for the BigQuery destination.

## 13. Checklist for another LLM

Before making code changes:

- [ ] Read this guide and `VPC_UAT.md`.
- [ ] Confirm the target GCP project and dataset.
- [ ] Confirm the Linxa preset ID, currently expected to be `284` for the tested CDR layout.
- [ ] Confirm `serviceType` and report timezone.
- [ ] Confirm whether masked data is sufficient.
- [ ] Confirm Secret Manager secret name and runtime service account.
- [ ] Confirm the VPC connector is `READY` in `europe-west2`.
- [ ] Run a one-row masked API test.
- [ ] Run one small time-window extraction.
- [ ] Validate row counts, headers, durations, and duplicate CDR IDs.
- [ ] Only then design the staging and final BigQuery tables.

## 14. Credential handling note

The source API notes and previous terminal commands may contain credentials. Treat those values as compromised if they were real. Rotate them with Linxa and replace them with placeholders or Secret Manager references before committing documentation.