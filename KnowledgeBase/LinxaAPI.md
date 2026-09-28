Linxa Connect API (OpenAPI 3.1) - Base URL: https://pccwg.linxa.com/api/connect

AUTH:
- POST /auth/v1/validate-credential -> Login & obtain JWT Bearer token
- POST /auth/v1/refresh-token -> Refresh existing session token

CARRIERS:
- POST /v1/carriers/get -> Carrier details & metadata
- POST /v1/carrier-overview/get -> Carrier high-level overview

ROUTING:
- POST /v1/routing-tree/get -> Fetch routing tree
- POST /v1/routing-test -> Run routing simulation on digits
- POST /v1/percentage-routing/get -> Weighted load sharing rules
- POST /v1/granular-routing/get -> Granular route policies
- POST /v1/exceptional-routing/get -> Override / exceptional routes

TRAFFIC CONTROL & SECURITY:
- POST /v1/blockings/get -> Active blocking policies
- POST /v1/blacklist/get -> Blacklisted prefixes/IPs
- POST /v1/whitelist/get -> Whitelisted prefixes/IPs
- POST /v1/unknownNumbers/get -> Unmapped/unknown destination numbers

ANALYTICS & CDR ARCHIVE:
- POST /v1/report-builder/getReport -> Custom multi-metric report generator
- POST /v1/cdr-archive/getSummaryReport -> CDR aggregated summaries
- POST /v1/cdr-archive/getRatedReport -> Rated CDR itemized call logs

CLOUD NUMBERS & OBR RATES:
- POST /v1/cloud-Number-management/selling/get -> Fetch selling numbers
- POST /v1/cloud-Number-management/selling/number -> Configure selling number
- POST /v1/cloud-Number-management/rates/get -> Fetch origin-based rates (OBR)
- POST /v1/cloud-Number-management/buying/number -> Add buying number
- POST /v1/cloud-Number-management/buying/update -> Update buying number

LOGGING & AUDIT:
- GET/POST /v1/log/get -> System application & execution logs
- GET/POST /v1/user/session-log/get -> User session activity logs


# Linxa Connect API Data Schemas Reference (OAS 3.1)

This reference documents all **Data Transfer Objects (DTOs)** and request/response schemas exposed by the Linxa Connect API (`pccwg.linxa.com`). It is formatted for direct ingestion by code generators, TypeScript/Python type definitions, and AI models.

---

## 1. Common & Base Utility Schemas

### BaseResponse
Common wrapper for all API responses indicating operational status.
* `responseCode` (*integer, int32*): HTTP/Application status code (e.g., `200`, `400`, `500`).
* `message` (*string*): Descriptive status message or error detail.

### Range
Defines pagination or quantitative range boundaries.
* `min` (*integer / float*): Lower bound value.
* `max` (*integer / float*): Upper bound value.

### SafeDate
Encapsulates date/time filters safely across timezones.
* `date` (*string, ISO-8601*): Date value (e.g., `2026-09-08T00:00:00Z`).
* `format` (*string*): Date format specifier (e.g., `YYYY-MM-DD`).

---

## 2. Authentication Schemas

### AuthorizationRequest
* `username` (*string*): Operational user or API client identifier.
* `password` (*string*): Plaintext or hashed account secret.

### AuthorizationResponse
* `accessToken` (*string*): JWT bearer authorization token.
* `tokenType` (*string*): Token standard (typically `Bearer`).
* `expiresIn` (*integer*): Token validity lifetime in seconds.

### RefreshTokenRequest
* `refreshToken` (*string*): Valid session refresh token used to generate a new Bearer JWT.

---

## 3. Carrier & Account Management Schemas

### CarrierRequest
* `carrierId` (*integer / string*): Optional filter by unique carrier ID.
* `carrierName` (*string*): Optional search string for carrier name.
* `isActive` (*boolean*): Filter by active account status.

### CarrierData
* `carrierId` (*integer*): Unique account key.
* `carrierName` (*string*): Display name of the wholesale carrier.
* `accountType` (*string*): Account classification (`BUYER`, `SELLER`, `BOTH`).
* `currency` (*string*): ISO currency code (e.g., `USD`, `EUR`).
* `status` (*string*): Carrier operational status (`ACTIVE`, `SUSPENDED`).

### CarriersResponse
* `carriers` (*array<CarrierData>*): List of retrieved carrier records.
* `totalCount` (*integer*): Total matching records.

### CarrierOverviewRequest
* `startDate` (*string, ISO-8601*): Query window start.
* `endDate` (*string, ISO-8601*): Query window end.
* `filters` (*CarrierOverviewRequestFilters*): Contextual filters for summary aggregation.

### CarrierOverviewRequestFilters
* `carrierIds` (*array<integer>*): Filter list of carrier IDs.
* `trafficType` (*string*): Traffic category (`VOICE`, `SMS`).

---

## 4. Routing Configuration Schemas

### RoutingTreeRequest
* `routingTreeId` (*integer*): Identifier of the active dynamic routing tree.
* `destinationPrefix` (*string*): E.164 country/city prefix to evaluate.

### RoutingTestRequest
* `sourceNumber` (*string, E.164*): Originating A-number.
* `destinationNumber` (*string, E.164*): Terminating B-number.
* `carrierId` (*integer*): Ingress carrier account ID.

### PercentageRoutingRequest / GranularRoutingRequest / ExceptionalRoutingRequest
* `routeId` (*integer*): Unique identifier for the routing rule.
* `carrierId` (*integer*): Carrier account ID associated with the rule.
* `prefix` (*string*): Prefix matching rule (e.g., `44` for UK).
* `isActive` (*boolean*): Rule toggle state.

### PercentageRoutingData / GranularRoutingData / ExceptionalRoutingData
* `ruleId` (*integer*): Rule ID.
* `priority` (*integer*): Route priority ranking.
* `weight` (*integer / float*): Percentage share allocation (for percentage routing).
* `carrierId` (*integer*): Assigned egress partner.
* `trunkGroup` (*string*): Switch/SBC trunk group target.

### PercentageRoutingResponse / GranularRoutingResponse / ExceptionalRoutingResponse
* `data` (*array<RoutingData>*): List of dynamic routing rule objects.

---

## 5. Traffic Control & Security Schemas

### WhitelistRequest / BlacklistRequest / BlockingRequest
* `number` (*string*): Specific E.164 number or prefix string.
* `comment` (*string*): Administrative audit note or reason code.
* `updatedBy` (*string*): Username/API user making the modification.
* `startDate` (*string, ISO-8601*): Rule activation timestamp.
* `endDate` (*string, ISO-8601*): Rule expiration timestamp.
* `isBlocked` (*boolean*): Blocking flag (`true` = block, `false` = allow).

### WhitelistData / BlacklistData / BlockingData
* `id` (*integer*): Entry key.
* `number` (*string*): Prefixes/numbers targeted by the rule.
* `comment` (*string*): Reason for entry.
* `updatedBy` (*string*): User who created/updated entry.
* `startDate` (*string*): Active start date.
* `endDate` (*string*): Active end date.
* `isBlocked` (*boolean*): Enforced state.

### WhitelistResponse / BlacklistResponse / BlockingResponse
* `whitelistData` / `blacklistData` / `blockingData` (*array<Object>*): List of security entries.

### UnknownNumberRequest / UnknownNumberData / UnknownNumberResponse
* `number` (*string*): Destination digit sequence unmatched in prefix routing tables.
* `attemptCount` (*integer*): Total attempts received for unmapped destination.
* `lastSeen` (*string, ISO-8601*): Timestamp of last call attempt.

---

## 6. Analytics & CDR Schemas

### ReportBuilderRequest
* `presetId` (*string / integer, tenant-specific; observed in Report Builder requests*): Saved Report Builder preset identifier. A preset is valid only for the endpoint and tenant where it is configured.
* `serviceType` (*string; observed value `V` for voice*): Traffic/service type requested by the preset.
* `showMasked` (*boolean*): Requests masked number fields where supported. Prefer `true` for analytics and chatbot use.
* `metrics` (*array<string>*): KPI metrics requested (e.g., `ASR`, `NER`, `ACD`, `DURATION`, `ATTEMPTS`, `REVENUE`).
* `groupBy` (*array<string>*): Dimensions for data aggregation (e.g., `START_DATE`, `COUNTRY`, `CARRIER`).
* `startDate` (*string, ISO-8601*): Analytics query start time.
* `endDate` (*string, ISO-8601*): Analytics query end time.
* `filters` (*ReportBuilderRequestFilters*): Filter parameters.
* `range` (*object; behavior not verified for Report Builder*): Candidate pagination fields `start` and `length`; do not assume the endpoint honors them.

### Observed Report Builder response
* `dataList` (*array<object>*): Report rows. A successful request with preset `2756` returned this property as an array of 10,000 objects.
* Observed keys included `ASR`, `Destination`, `ACD`, `Outgoing_Carrier`, `Incoming_Trunk`, `Incoming_Account`, `Successful_Calls`, `Unsuccessful_Calls`, `Call_Attempts`, `Incoming_Carrier`, `Outgoing_Account`, `Outgoing_Trunk`, `Destination_Country`, `NER`, `Duration_(Minutes)`, and `Answered_Calls`.
* The API returned 10,000 rows despite requesting `range.length=1`; changing `range.start` to `10000` returned the same first row. Pagination is unverified.
* Date filters were included in the successful request, but the result had no date field proving that the requested window was applied. Validate against Linxa UI before relying on date-specific values.

### ReportBuilderRequestFilters
* `carrierIds` (*array<integer>*): Filter by carrier IDs.
* `countryCodes` (*array<string>*): Filter by destination country ISO codes.
* `successfulCallsOnly` (*boolean*): Restricts output to completed calls.

### CdrArchiveSummaryRequest
* `presetId` (*string / integer, tenant-specific*): CDR Archive preset ID. Do not assume a Report Builder preset ID is valid here.
* `serviceType` (*string; tested value `V` for voice*): Service type.
* `showMasked` (*boolean*): Prefer `true` unless unmasked fields are explicitly required and authorized.
* `filters.from` / `filters.to` (*string*, tested format `YYYY-MM-DD HH:mm`): CDR Archive date/time filter.
* `range.start` / `range.length` (*integer*): Offset/page candidate. CDR Archive accepted these in tested requests; large offsets can be slow or return `403`.

### CdrArchiveRatedRequest
* `presetId`, `serviceType`, `showMasked`, filters, and range may differ from the Summary request. Confirm the live OpenAPI schema before calling; do not infer that Report Builder fields apply.

### Endpoint separation
* Saved Report Builder preset: `POST /v1/report-builder/getReport`.
* CDR Archive summary: `POST /v1/cdr-archive/getSummaryReport`.
* A saved Report Builder preset `2756` returned HTTP `200` on `getReport` but `Preset does not exists` on `getSummaryReport` with the UAT credential.

### CdrArchiveRatedRequestFilters
* `callId` (*string*): Unique SIP Call-ID string.
* `cli` (*string*): Calling Line Identification (A-Number).
* `cld` (*string*): Called Party Number (B-Number).
* `disconnectCause` (*integer*): SIP or Q.850 cause code.

---

## 7. Cloud Number & Rating Schemas

### NumberManagementSellingRequest / NumberManagementUpdateSellingRequest
* `number` (*string, E.164*): Selling DID/virtual number.
* `carrierId` (*integer*): Assigned wholesale buyer.
* `monthlyFee` (*float*): Recurring cost.
* `perMinuteRate` (*float*): Inbound/outbound usage rate.

### NumberManagementSellingData / NumberManagementSellingResponse
* `number` (*string*): Managed phone number.
* `status` (*string*): Status (`AVAILABLE`, `ASSIGNED`, `RESERVED`).
* `carrierName` (*string*): Assigned carrier.

### NumberManagementRateRequest / OriginBasedRatesData
* `originPrefix` (*string*): A-Number prefix for Origin-Based Rating (OBR).
* `destinationPrefix` (*string*): B-Number prefix for destination rating.
* `rate` (*float*): Pricing per minute/message.
* `effectiveDate` (*string, ISO-8601*): Price activation date.

---

## 8. Logging & Session Schemas

### LogRequest / LogData / LogResponse
* `logLevel` (*string*): Log severity (`INFO`, `WARN`, `ERROR`, `DEBUG`).
* `module` (*string*): System component (`ROUTING`, `BILLING`, `AUTH`).
* `message` (*string*): Diagnostic log payload text.
* `timestamp` (*string, ISO-8601*): Execution timestamp.

### UserSessionRequest / UserSessionData / UserSessionResponse
* `userId` (*string / integer*): Operational user key.
* `ipAddress` (*string*): Client IP address.
* `loginTime` (*string, ISO-8601*): Session initiation timestamp.
* `active` (*boolean*): Current active session flag.

---

## 9. TypeScript Interface Definitions (Quick AI Ingestion)

```typescript
export interface BaseResponse {
  responseCode: number;
  message: string;
}

export interface WhitelistEntry {
  number: string;
  comment?: string;
  updatedBy?: string;
  startDate?: string;
  endDate?: string;
  isBlocked: boolean;
}

export interface ReportBuilderRequest {
  presetId: string;
  serviceType: string;
  showMasked: boolean;
  metrics: Array<'ASR' | 'NER' | 'ACD' | 'DURATION' | 'ATTEMPTS' | 'REVENUE'>;
  groupBy: Array<'START_DATE' | 'COUNTRY' | 'CARRIER' | 'PREFIX'>;
  startDate: string;
  endDate: string;
  filters?: {
    carrierIds?: number[];
    countryCodes?: string[];
    successfulCallsOnly?: boolean;
    from?: string;
    to?: string;
  };
  /** Pagination was not demonstrated; the endpoint returned 10,000 rows for length=1. */
  range?: { start: number; length: number };
}

export interface ReportBuilderResponse {
  dataList: Array<Record<string, unknown>>;
}

export interface CdrArchiveSummaryRequest {
  presetId: string;
  serviceType: string;
  showMasked: boolean;
  filters: { from: string; to: string };
  range?: { start: number; length: number };
}

export interface RoutingTestRequest {
  sourceNumber: string;
  destinationNumber: string;
  carrierId?: number;
}

export interface CdrSearchFilters {
  callId?: string;
  cli?: string;
  cld?: string;
  disconnectCause?: number;
  startDate: string;
  endDate: string;
}


## Credentials

This file intentionally contains no credentials.

The Linxa API authorization credential is stored in Google Cloud Secret Manager:

- Secret name: `linxa-api-authorization`
- Project: `pccw-internal-virt-agent-uat`
- Full resource path: `projects/pccw-internal-virt-agent-uat/secrets/linxa-api-authorization/versions/latest`
- IAM: `pccw-internal-virt-agent-uat@appspot.gserviceaccount.com` has `roles/secretmanager.secretAccessor` on the secret.

How to reference it:

- Python (repo pattern, see `shared/secrets_manager.py`):
  ```python
  from shared.secrets_manager import get_secret
  credential = get_secret("linxa-api-authorization", project_id="pccw-internal-virt-agent-uat")
  ```
- gcloud (local testing; never print the value):
  ```powershell
  $cred = gcloud secrets versions access latest --secret=linxa-api-authorization --project=pccw-internal-virt-agent-uat
  # Use as: Authorization = $cred  (raw credential format: "<id>:<key>")
  ```
- Cloud Function runtime: use Secret Manager volume mount or
  `--set-secrets LINXA_AUTHORIZATION=linxa-api-authorization:latest` at deploy time.

If this credential is ever exposed in a file, log, chat, or terminal history, rotate it with Linxa and add a new secret version:
`gcloud secrets versions add linxa-api-authorization --project=pccw-internal-virt-agent-uat --data-file=-`