# Helix Trouble Ticketing v8 - Field and Operation Matrix

## Purpose
- Provide a strict, implementation-facing matrix for validation and payload construction.
- Separate model-level fields from operation-level constraints.
- Capture known ambiguities so automation logic handles them explicitly.

## Source baseline
- Primary notes: HELIX_ServiceSpec_v8_Detailed_Notes.md
- Underlying converted spec mirror: shared/Helix - Service spec v8 - Internal.docx.md
- Tenant behavior must still be validated in UAT before production assumptions.

## A. Core troubleTicket field matrix

| Field | Type | In model | Create (spec) | Patch (spec) | Notes for automation |
| --- | --- | --- | --- | --- | --- |
| @type | String | Implied by payload examples | Required by tenant behavior; expected troubleTicket | Required by tenant behavior for PATCH body | Always send as troubleTicket for create and patch requests. |
| id | String | Yes | Server generated | Path parameter only | Never client-set on create. |
| name | String | Yes | Mandatory | Patchable | Map from Jira summary; fallback required if missing. |
| description | String | Yes | Optional | Patchable | Map from Jira description; append the Jira source trace plus metadata block so created/updated/resolved/assignee/resolution are visible in the Remedy ticket. |
| externalId | String | Yes | Optional | Patchable | Use Jira key as externalId for deterministic traceability. |
| priority | String | Yes | Mandatory | Not listed patchable | Use explicit default Low unless mapped rules exist. |
| ticketType | String | Yes | Mandatory; default Incident also stated | Not listed patchable | Set explicitly to Incident to avoid ambiguity. |
| status | String | Yes | Optional; default Acknowledged if omitted | Patchable with workflow limits | Do not rely on unrestricted transitions without live validation. |
| creationDate | DateTime | Yes | Optional; defaults to current system time if omitted | Not listed patchable | Candidate for backdate test; may be ignored/rejected by tenant. |
| lastUpdate | DateTime | Yes | Server managed | Server managed | Read-only from consumer perspective. |
| channel.name | String | Yes | Optional; default API | Not listed patchable | Set explicitly to API for consistency. |
| channel.@type | String | Yes | Optional; default Customer | Not listed patchable | Set explicitly to Customer unless business requires different. |
| relatedEntity[] | Array | Yes | Required in practice for customer mapping; customerId/sr key pair highlighted | Not listed patchable | Must include customerId relation at minimum. |
| relatedParty[] | Array | Yes | Optional | Patchable only for role Contact | Do not use for assignment routing unless API owner confirms behavior. |
| notes[] | Array | Yes | Required by create rules for faultsymptom in spec table | Patchable only to append worklog notes | Create and patch note types follow different constraints. Current validated create payload uses the `category/item/type = Others` trio. |
| troubleTicketRelationship[] | Array | Yes | Optional | Not listed patchable | Usually omit unless needed by workflow. |

## B. Notes field subtype matrix

| Context | Required note shape per spec | Operational behavior guidance |
| --- | --- | --- |
| Create | notes.@type value faultsymptom; notes.id Item mandatory for symptom description; notes.text from Section 5.2 list | Tenant runbooks show category/item/type faultsymptom trio has been accepted in UAT and PROD dry-run validation. Preserve existing known-good pattern unless API owner instructs otherwise. |
| Patch worklog | notes only allows adding new notes where @type is worklog | Build additive worklog patches only; do not attempt full notes replacement. |
| notes.date | Present in model | Not guaranteed to be accepted in patch requests. Test explicitly before relying on timestamp backfill in native note date field; current scripts preserve timestamps in text and audit logs instead. |
| notes.author | Present in model | Not guaranteed to be accepted for worklog patch in current route; treat as optional test item. |

## C. relatedEntity role guidance matrix

| Role | Usage | Expected source |
| --- | --- | --- |
| customerId | Primary selection and linkage key | Jira mapped customer field or organization mapping |
| srId | Secondary key (optional in list filters and create context) | Jira SR fields if available |
| serviceId | Mentioned in runbook examples | Only send when validated and available |

## D. Operation matrix

| Operation | Method + URL | Required headers (spec) | Required payload/params | Key constraints |
| --- | --- | --- | --- | --- |
| Create | POST /cs-helix-ticketing/internalHelix/troubleTicket | Authorization | troubleTicket object | Mandatory: name, priority, ticketType, faultsymptom note requirements, relatedEntity key mapping. |
| Retrieve | GET /cs-helix-ticketing/internalHelix/troubleTicket/{id} | Authorization | id path param | Returns full ticket details. |
| List | GET /cs-helix-ticketing/internalHelix/troubleTicket?filters | Authorization | relatedEntity.customerId and status indicated mandatory | status default wording conflicts with mandatory wording; safest is provide both always. |
| Patch | PATCH /cs-helix-ticketing/internalHelix/troubleTicket/{id} | Authorization | troubleTicket patch object | Patchable fields constrained; notes only append worklog. |
| Delete | DELETE /cs-helix-ticketing/internalHelix/troubleTicket/{id} | Content-Type, Authorization, userKey | id path param | Logical cancel only; status becomes Cancelled. |

## E. Status workflow matrix

| Status value | In enum list | Create behavior | Patch behavior from spec text | Automation caution |
| --- | --- | --- | --- | --- |
| ACKNOWLEDGED | Yes | Default when omitted | Not stated as patch target | Common initial server status. |
| IN PROGRESS | Yes | Valid value | Re-open target from RESOLVED | Explicitly referenced in patch workflow constraint. |
| PENDING | Yes | Enum present | Not specified | Requires tenant validation. |
| RESOLVED | Yes | Enum present | Source state in reopen constraint | Transition behavior tenant-specific. |
| CLOSED | Yes | Enum present | Not explicitly allowed in patch table | Must validate with live API before depending on close patch flow. |
| CANCELLED | Yes | Enum present | Delete operation yields cancelled | Available as cancel semantic, not equivalent to closed. |
| REJECTED | Yes | Enum present | Not specified | Validation required. |
| HELD | Yes | Enum present | Not specified | Validation required. |

## F. Enumerations inventory

### Priority (text available)
- CRITICAL
- HIGH
- MEDIUM
- LOW

### Status types (text available)
- ACKNOWLEDGED
- IN PROGRESS
- PENDING
- RESOLVED
- CLOSED
- CANCELLED
- REJECTED
- HELD

### Item and Fault caused (not fully text-extracted)
- Section 5.2 Item appears as image in conversion.
- Section 5.5 Fault caused appears as image in conversion.
- Action:
  - Obtain machine-readable enum list from API owner or direct doc export with complete text.
  - Store a local enum file for validator checks before create.

## G. Validation rules for implementation

Recommended pre-flight payload checks before API calls:
- Create:
  - name non-empty
  - priority in allowed set
  - ticketType explicit (Incident)
  - relatedEntity includes customerId
  - notes has required create symptom pattern accepted by tenant
- Patch worklog:
  - root @type present
  - notes array non-empty
  - each note @type is worklog
- Status patch:
  - block unsupported transitions behind feature flag until validated
- Delete:
  - ensure userKey source exists if using cancel operation

## H. Known ambiguities and handling strategy
- ticketType marked mandatory but also defaulted in spec text.
  - Handling: always set explicitly.
- List status marked mandatory but also says default IN PROGRESS if absent.
  - Handling: always provide status.
- Model contains notes.date and notes.author, but route-level acceptance not guaranteed.
  - Handling: probe in UAT first; fallback to embedding timestamps in worklog text and audit store.

## I. Suggested companion enum file format
- File suggestion: HELIX_ServiceSpec_v8_Enums.json
- Keys:
  - priority
  - status
  - item
  - faultCaused
  - ticketType
- Use this for deterministic request validation and CI tests.
