# Helix Trouble Ticketing API Spec v8 - Detailed Notes

## Scope and intent
- Source document title: Trouble Ticketing API Specification.
- Internal platform scope: PCCWG internal access via API Gateway.
- Standards alignment called out in spec:
  - MEF 55 (LSO Sonata Trouble Ticketing API Project)
  - TMF621 Trouble Ticket API REST Specification (release 19.0.1)
- API style: REST over HTTPS, synchronous request-response for all listed operations.

## Change history in spec
- Issue 1 (11-02-2020): Initial draft.
- Issue 2 (28-02-2020): Search multiple ticket API updates and work log APIs added.
- Issue 3 (09-04-2020): MEF/TMF compliance updates.
- Issue 4 (02-11-2020): CTI-related field updates and MSSL information.
- Issue 5 (23-02-2021): Reported source restricted to "API" and ticket category/type changes in create API.
- Issue 6 (28-10-2022): Internal platform access method updates.
- Issue 7 (30-03-2026): Latest TYK information updates.

## Access and auth model
- Gateway migration note: WSO2 to TYK (2024 migration).
- Access requirement: Auth0 account.
- Typical onboarding reference ticket in spec: CSCM-18391.
- Caller must provide system ID/name during onboarding.
- JWT acquisition endpoint and required form fields:
  - POST https://auth.stage.consoleconnect.com/oauth/token
  - grant_type=client_credentials
  - client_id={client id}
  - client_secret={client secret}
  - audience=api.stage.corp.consoleconnect.com
- Authorization model for ticket APIs: Bearer JWT in Authorization header.

## Domain model (Trouble Ticket object)
Top-level fields listed by spec:
- creationDate (DateTime): creation timestamp.
- lastUpdate (DateTime): last update timestamp.
- description (String): issue description.
- externalId (String): external-system reference ID.
- id (String): unique trouble ticket ID.
- name (String): short ticket name/summary.
- priority (String): urgency band (examples: Critical/High/Medium/Low).
- status (String): current ticket status.
- ticketType (String): business ticket type (example: Incident).
- channel (Object): source channel metadata.
- relatedParty (Array): contact/party metadata.
- notes (Array): freeform notes/worklogs/fault detail records.
- relatedEntity (Array): linked entities (customer/service/etc).
- troubleTicketRelationship (Array): ticket-to-ticket relationships.

Sub-structures listed in spec:
- channel:
  - @type (String), examples include Customer/Internal/Proactive/Supplier/Supplier Proactive.
  - name (String), example API.
- relatedParty:
  - phone/email/name/role.
  - role examples include Contact, Assigned Group (model-level examples only).
- notes:
  - id, text, date, author, @type.
  - @type examples include worklog, faultsymptom, faultlocation, faultcause, faultreason.
  - attachment array with content (base64), name, size, href.
  - attachment limits from model section: size up to 10M, max count 3.
- relatedEntity:
  - name, role, @type, @referredType.
- troubleTicketRelationship:
  - name, relationshipType.

## Error model
- Error envelope fields:
  - error.code
  - error.title
  - detail
- Enumerated error codes:
  - 001: Internal Error.
  - 002: Workflow, state transition is not valid.
  - 003: Workflow, invalid operation for state.
  - 004: Input validation error (missing mandatory fields, wrong parameter type, etc).

## API operations summary
- 4.1 Create trouble ticket: POST /cs-helix-ticketing/internalHelix/troubleTicket
- 4.2 Retrieve by ID: GET /cs-helix-ticketing/internalHelix/troubleTicket/{id}
- 4.3 List with filters: GET /cs-helix-ticketing/internalHelix/troubleTicket?{filters}
- 4.4 Patch existing ticket: PATCH /cs-helix-ticketing/internalHelix/troubleTicket/{id}
- 4.5 Delete (cancel semantics): DELETE /cs-helix-ticketing/internalHelix/troubleTicket/{id}

## 4.1 Create trouble ticket - detailed contract notes
Endpoint and headers:
- Method: POST
- URL: /cs-helix-ticketing/internalHelix/troubleTicket
- Required header from operation table: Authorization: Bearer {Jwt token}

Mandatory attributes/rules called out in spec text:
- troubleTicket.name: mandatory.
- troubleTicket.priority: mandatory.
- troubleTicket.ticketType: mandatory, with default value "Incident" indicated.
- notes.@type: value must be "faultsymptom" in create flow context.
- notes.id: note.id="Item" is explicitly called mandatory to describe fault symptom.
- notes.text: must use allowed item values from Section 5.2.
- relatedEntity: service profile on customer id and sr id are key pairs to the ticket.

Non-mandatory attributes/rules called out:
- troubleTicket.description: optional.
- troubleTicket.creationDate: optional; if empty, system defaults to current system datetime.
- troubleTicket.externalId: optional; for customer-system unique ID mapping.
- troubleTicket.status: optional; if empty defaults to Acknowledged.
- relatedParty: optional; keeps one contact person and does not impact master contact data.
- notes: listed under non-mandatory table context, but create rules above still require faultsymptom shape for symptom description.
- channel.name: optional; default API.
- channel.@type: optional; default Customer.
- relatedEntity: optional for additional entity types beyond core keys (for example voice subscription information).

Operational interpretation:
- The create contract is not a free-form TMF payload; it has tenant-specific mandatory constraints around fault symptom notes and entity keys.
- "Default value Incident" appears for ticketType while also being marked mandatory in same table text; implementation should treat ticketType as explicitly set to avoid ambiguity.

## 4.2 Retrieve by ID - detailed contract notes
Endpoint and headers:
- Method: GET
- URL: /cs-helix-ticketing/internalHelix/troubleTicket/{id}
- Required header: Authorization: Bearer {Jwt token}
- Input parameter:
  - id (String), mandatory, unique ticket ID.
- Response note:
  - success response returns all levels of attributes (not only first-level).

## 4.3 List tickets - detailed contract notes
Endpoint and headers:
- Method: GET
- URL: /cs-helix-ticketing/internalHelix/troubleTicket?{filters}
- Required header: Authorization: Bearer {Jwt token}

Filter contract text:
- relatedEntity.customerId: mandatory for selection.
- status: mandatory in table text.
- relatedEntity.sr: optional.
- Additional caveat in spec text:
  - Not all first-level troubleTicket attributes are filterable.
  - Status defaults to IN PROGRESS if not provided.
  - Mentioned status values for filtering include ACKNOWLEDGED, IN PROGRESS, RESOLVED, CANCELLED.

Operational interpretation:
- There is mixed wording (status marked mandatory and defaulted if absent). safest client behavior is to always provide both customerId and status.

## 4.4 Patch trouble ticket - detailed contract notes
Endpoint and headers:
- Method: PATCH
- URL: /cs-helix-ticketing/internalHelix/troubleTicket/{id}
- Required header: Authorization: Bearer {Jwt token}

Patchability constraints from spec table:
- Patchable top-level fields:
  - description
  - externalId
  - name
  - status
  - relatedParty (restricted to role=Contact with phone/email/name)
  - notes
- Status restriction text:
  - Only allows re-open from RESOLVED back to IN PROGRESS through API.
  - Other status transitions are controlled by PCCWG ops teams in frontend.
- Notes restriction text:
  - Only allows adding new notes (with or without attachments) when @type is worklog.

Operational interpretation:
- PATCH is constrained. It is not a general overwrite endpoint.
- worklog append behavior should be treated as additive only.
- status transition capabilities may differ by tenant implementation/policy; runtime validation is still required.

## 4.5 Delete trouble ticket - detailed contract notes
Endpoint and headers:
- Method: DELETE
- URL: /cs-helix-ticketing/internalHelix/troubleTicket/{id}
- Required headers listed:
  - Content-Type: application/json
  - Authorization: Bearer {{token}}
  - userKey: Encrypted Insight account

Semantic behavior:
- Delete means logical cancel.
- Resulting status becomes Cancelled.

Operational interpretation:
- DELETE is effectively a status-changing operation rather than hard delete.
- userKey requirement is notable and can block automation if unavailable.

## Enumerations
### 5.2 Item
- Item list is represented as an embedded image in the source conversion.
- Text extraction does not contain a machine-readable list in this local mirror.
- Action needed for implementation hardening:
  - Obtain a typed list directly from API owner or from a machine-readable export.

### 5.3 Priority
- CRITICAL
- HIGH
- MEDIUM
- LOW

### 5.4 Trouble Ticket Status Types
- ACKNOWLEDGED
- IN PROGRESS
- PENDING
- RESOLVED
- CLOSED
- CANCELLED
- REJECTED
- HELD

### 5.5 Fault caused
- Fault caused list is represented as an embedded image in the source conversion.
- Text extraction does not contain a machine-readable list in this local mirror.

### 5.6 Ticket type
- Incident

## Cross-check notes against current Helix integration usage
Current integration pattern (as observed in local UAT/prod scripts) broadly aligns with spec in these areas:
- Uses POST create endpoint under /cs-helix-ticketing/internalHelix/troubleTicket.
- Sends Authorization bearer token and custom X-System-Id header (X-System-Id is implementation-specific, not in the spec tables, but accepted in tenant tests).
- Sends faultsymptom notes array in create flow.
- Uses PATCH with @type=worklog notes for comment sync.

Known divergences/ambiguities to track:
- Spec notes.id text says Item mandatory with specific naming conventions, while practical tenant tests accepted category/item/type faultsymptom tuple and worklog id conventions.
- Spec says PATCH status transition is constrained; tenant behavior should be empirically re-verified before assuming full close transitions.
- Spec indicates creationDate can be provided; tenant acceptance of caller-controlled backdated creationDate must be verified with direct API tests.

## Timestamp retention implications for duplication workflows
For Jira-closed-ticket duplication use cases:
- Desired exact preservation points:
  - Jira issue created timestamp.
  - Jira comment created/updated timestamps.
  - Jira closure timestamp.
- Spec-level possible fields:
  - troubleTicket.creationDate exists in create model and is optional.
  - notes.date exists in model, but patch rules narrow notes usage to worklog adds.
- Implementation caution:
  - Even if fields exist in model, tenant route may reject or ignore them depending on validation policy.
  - Always validate with direct create/patch/retrieve round-trip tests before promising exact native timestamp backfill.

## Practical test checklist derived from spec
- Auth tests:
  - Verify token with correct audience for target environment.
- Create tests:
  - Minimal mandatory payload acceptance.
  - notes.id/value compliance for faultsymptom items.
  - Explicit vs omitted ticketType behavior.
  - Explicit creationDate acceptance and round-trip retrieval check.
- Patch tests:
  - worklog append with minimal fields.
  - worklog append with date/author if needed for timestamp preservation.
  - status transition to target terminal state (CLOSED/RESOLVED/CANCELLED) for tenant.
- Delete tests:
  - userKey availability and behavior.
  - resulting status verification.
- List tests:
  - required filter combinations and default behavior.

## Gaps in this local mirror and how to close them
Gaps identified:
- Section 5.2 Item values are image-only in converted markdown.
- Section 5.5 Fault caused values are image-only in converted markdown.

Recommended closure steps:
- Export original doc to plain text or PDF with OCR-friendly tables/lists.
- Ask API owner for canonical enum artifacts (CSV/JSON/Confluence table).
- Store those enum lists in repo as plain markdown under the relevant Helix integration area for strict validation.

## Suggested companion files for future implementation
- A strict JSON schema for create payload and patch payload per tenant acceptance.
- A tenant-specific behavior matrix documenting:
  - accepted fields,
  - ignored fields,
  - rejected fields with representative error payloads.

## Reference locations used for these notes
- Spec mirror in repo:
  - shared/Helix - Service spec v8 - Internal.docx.md
- Raw extraction copy:
  - Temp/helix_spec_extracted.txt
- Existing tenant runbook context:
  - KnowledgeBase UAT runbook context


##create ticket request
https://api.stage.corp.consoleconnect.com/cs-helix-ticketing/internalHelix/troubleTicket
Bearer <jwt token>


{
    "name": "Packet Drop",
    "creationDate": "2026-03-20T05:05:05.000+0000",
    "description": "Testing from TYK internal API with Internal work log type, please ignore",
    "priority": "High",
    "ticketType": "Incident",
    "destination":"",
    "relatedParty": [
        {
            "name": "J Fung",
            "email": "jylfung@consoleconnect.com",
            "phone": "123456789"
        }
    ],
    "notes": [
        {
            "id": "Internal Work Log",
            "text": "For testing only, please ignore",
            "@type": "worklog"
        },
        {
            "id": "category",
            "text": "IPVPN",
            "@type": "faultsymptom"
        },
        {
            "id": "type",
            "text": "IPVPN",
            "@type": "faultsymptom"
        },
        {
            "id": "item",
            "text": "Circuit Down",
            "@type": "faultsymptom"
        },
                    {
            "id": "cause",
            "@type": "faultcause"
        },
        {
            "id": "Tokyo",
            "@type": "faultlocation"
        }       
    ],              
    "channel": {
        "name": "Web",  
        "@type":"Customer"
    },  
    "relatedEntity": [
        {
            "name": "TCNAI",
            "role": "customerId",
            "@type": "RelatedEntity",
            "@referredType": "Profile"
        },              
        {
            "name": "S0015241",
            "role": "srId",
            "@type": "RelatedEntity",
            "@referredType": "Profile"
        },
        {
            "name": "br123",
            "role": "breakout",
            "@type": "RelatedEntity",
            "@referredType": "Voice"
        }  
    ]   
    ,
    "@type": "troubleTicket"
}