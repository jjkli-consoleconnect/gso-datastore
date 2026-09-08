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
* `metrics` (*array<string>*): KPI metrics requested (e.g., `ASR`, `NER`, `ACD`, `DURATION`, `ATTEMPTS`, `REVENUE`).
* `groupBy` (*array<string>*): Dimensions for data aggregation (e.g., `START_DATE`, `COUNTRY`, `CARRIER`).
* `startDate` (*string, ISO-8601*): Analytics query start time.
* `endDate` (*string, ISO-8601*): Analytics query end time.
* `filters` (*ReportBuilderRequestFilters*): Filter parameters.

### ReportBuilderRequestFilters
* `carrierIds` (*array<integer>*): Filter by carrier IDs.
* `countryCodes` (*array<string>*): Filter by destination country ISO codes.
* `successfulCallsOnly` (*boolean*): Restricts output to completed calls.

### CdrArchiveSummaryRequest / CdrArchiveRatedRequest
* `startDate` (*string, ISO-8601*): CDR search window start time.
* `endDate` (*string, ISO-8601*): CDR search window end time.
* `filters` (*CdrArchiveSummaryRequestFilters* / *CdrArchiveRatedRequestFilters*): Specific CDR search conditions.

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
  metrics: Array<'ASR' | 'NER' | 'ACD' | 'DURATION' | 'ATTEMPTS' | 'REVENUE'>;
  groupBy: Array<'START_DATE' | 'COUNTRY' | 'CARRIER' | 'PREFIX'>;
  startDate: string;
  endDate: string;
  filters?: {
    carrierIds?: number[];
    countryCodes?: string[];
    successfulCallsOnly?: boolean;
  };
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


Key ID: 
1
API Key: 
!ZDtGmfygV9.gPHp