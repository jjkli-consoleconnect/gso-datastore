# HDWL AI Field Definitions

**Model:** Gemini 2.5 Flash (`gemini-2.5-flash`)
**Table:** `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
**View:** `pccw-internal-virt-agent-uat.GSO.HDWL`
**Prompt Version:** `hdwl-firstresponse-v16-device-regex-fallback`

> **Important for queries:** The `HDWL` view has **one row per worklog**. AI fields repeat per ticket.
> Always use `MAX()` or `ANY_VALUE()` per `Incident_Number` to get one AI result per ticket.

---

## Field Reference

### AIFirstResponse
- **Type:** STRING (free text, max 500 chars)
- **What it is:** The exact text of the first meaningful customer-facing response from a NOC agent.
- **How it's derived:** Scans `Email-Progress Update` and `Internal Work Log (Email)` worklogs for the earliest entry that provides a substantive update, investigation finding, or targeted troubleshooting question directed at the customer. Acknowledgement-only messages and ticket-creation notifications are excluded.
- **Null when:** No meaningful customer-facing response exists in the worklogs.

---

### AIFirstResponseTimestamp
- **Type:** TIMESTAMP (ISO 8601)
- **What it is:** Timestamp of the worklog entry identified as `AIFirstResponse`.
- **How it's derived:** Derived alongside `AIFirstResponse` using the same selection criteria.
- **Null when:** No meaningful response found.

---

### AIFirstResponse_Audit
- **Type:** STRING (free text, max 200 chars)
- **What it is:** One-sentence explanation of why the chosen worklog was (or was not) selected as the first meaningful response.
- **How it's derived:** AI-generated reasoning justifying the `AIFirstResponse` selection.

---

### AIAtFault ⚠️ Controlled values
- **Type:** STRING
- **What it is:** Who bears accountability for the fault.
- **How it's derived:** Primary source — `Fault_Cause` and `Fault_Cause_Detail` fields. Secondary — worklog content.
- **Allowed values:**

  | Value | Meaning |
  |---|---|
  | `Customer` | Root cause is customer equipment, configuration, or action |
  | `Carrier/Vendor` | Far-end partner, peering, or third-party provider fault |
  | `PCCW` | PCCW network, platform, provisioning, or operations fault |
  | `Nobody` | No fault found, right-when-tested, maintenance, or insufficient evidence to assign blame |

---

### AIAtFault_Audit
- **Type:** STRING (free text, max 200 chars)
- **What it is:** One-sentence justification citing the key evidence used for the `AIAtFault` classification.
- **How it's derived:** AI-generated reasoning referencing `Fault_Cause`, `Fault_Cause_Detail`, or worklog phrases.

---

### AI_FaultDomain ⚠️ Controlled values
- **Type:** STRING
- **What it is:** Which technical network domain the fault belongs to.
- **How it's derived:** Based on device names, interface types, symptoms, and worklog content. Worklog evidence takes priority over `Fault_Cause` metadata.
- **Allowed values:**

  | Value | Meaning |
  |---|---|
  | `Access` | Last-mile, access port, DSL, optical access |
  | `Core` | Backbone, routing, switching, IP/MPLS |
  | `CPE` | Customer premises equipment (router, ONT, NTU) |
  | `Power` | Power failure, UPS, generator |
  | `Security` | DDoS, BGP hijack, firewall |
  | `External` | Carrier/provider/peering fault outside PCCW infrastructure |
  | `Unknown` | Insufficient evidence to classify |

---

### AI_CarrierVendor
- **Type:** STRING (free text, comma-separated, max 3 names, max 200 chars)
- **What it is:** Name(s) of the external carrier or vendor involved in the fault, extracted from worklogs.
- **How it's derived:** AI extracts telco/provider entity names from worklog text using telco domain knowledge. Normalizes common variants (e.g. "TATA" → "Tata Communications").
- **Examples:** `"Tata Communications"`, `"NTT, HKT"`, `"China Telecom"`
- **Value when none found:** `"Unknown"`

---

### AI_PrimarySymptom
- **Type:** STRING (free text, max 150 chars)
- **What it is:** Concise description of the main observable fault symptom.
- **How it's derived:** What engineers and customers described in worklogs as the fault behavior.
- **Examples:** `"complete loss of BGP session"`, `"high packet loss on customer port"`, `"intermittent port flaps"`

---

### AI_LikelyRootCause
- **Type:** STRING (free text, max 200 chars)
- **What it is:** Technical root cause hypothesis grounded in worklog evidence.
- **How it's derived:** Uses confirmed root cause if stated in worklogs; otherwise best inference from available evidence. Worklog content takes priority over `Fault_Cause` metadata.
- **Examples:** `"fiber cut on access segment"`, `"BGP misconfiguration by carrier"`, `"power failure at remote site"`

---

### AI_ConfidenceScore
- **Type:** FLOAT64 (range: 0.0 – 1.0)
- **What it is:** How certain the AI is in its classifications, based on evidence quality in the worklogs.
- **How it's derived:** AI self-assessment of evidence completeness and clarity.

  | Range | Meaning |
  |---|---|
  | `0.8 – 1.0` | Explicitly confirmed in worklogs |
  | `0.5 – 0.7` | Inferred from partial evidence |
  | `0.2 – 0.4` | Very limited information available |

---

### AI_EvidenceSummary
- **Type:** STRING (free text, max 200 chars)
- **What it is:** Single strongest piece of evidence supporting the AI classifications. Quotes key worklog phrases or data points.
- **How it's derived:** AI identifies the most decisive evidence across all enrichment fields.

---

### AI_DeviceInterfaceContext
- **Type:** STRING (free text, max 300 chars)
- **What it is:** Device names, interface IDs, circuit IDs, or network path information relevant to the fault.
- **How it's derived:** AI extracts device/interface/circuit identifiers from worklog text. A regex pattern (`[A-Za-z]{2,3}[0-9]{2,3}\.[A-Za-z]{2,3}[0-9]{2,3}`) pre-extracts candidate device name tokens from worklogs as hints for the AI. If the AI returns no result, the regex candidates are used as fallback.
- **Examples:** `"PE1-HK ge-0/0/2.100, circuit CC-HK-1234"`, `"rt01.hkg, rt02.sin"`
- **Value when none found:** `"Unknown"`

---

## Metadata Fields

| Field | Type | Description |
|---|---|---|
| `ClassifiedAt` | TIMESTAMP | When the AI enrichment was written |
| `ModelName` | STRING | AI model used (e.g. `gemini-2.5-flash`) |
| `PromptVersion` | STRING | Prompt identifier (e.g. `hdwl-firstresponse-v16-device-regex-fallback`) |
| `PayloadHash` | STRING | SHA256 hash of inputs used; changes trigger re-classification |

---

## Usage Notes

- **Dashboard filter recommended:** `PromptVersion = 'hdwl-firstresponse-v16-device-regex-fallback'` to ensure consistent field semantics across versions.
- **Per-ticket aggregation:** `MAX(AIAtFault)`, `MAX(AI_FaultDomain)`, `MAX(AI_ConfidenceScore)` etc. when grouping by `Incident_Number`.
- **AIAtFault vs AI_FaultDomain:** `AIAtFault` = accountability (who), `AI_FaultDomain` = technical domain (where/what).
- **AI_CarrierVendor vs AIAtFault:** `AIAtFault = 'Carrier/Vendor'` means a carrier/vendor is to blame; `AI_CarrierVendor` names the specific entity (e.g. `"Tata Communications"`).
