SELECT 1 AS SortOrder, 'AIFirstResponse' AS Field, 'Exact text of the first meaningful customer-facing response. Source: Email-Progress Update and Internal Work Log (Email) worklogs only. Excludes acknowledgements and ticket-creation notifications.' AS Meaning, 'Free text' AS FieldType, NULL AS AllowedValues
UNION ALL
SELECT 2, 'AIFirstResponseTimestamp', 'Timestamp of the worklog identified as the first meaningful customer-facing response.', 'Timestamp', NULL
UNION ALL
SELECT 3, 'AIFirstResponse_Audit', 'One-sentence explanation of why a worklog was selected, or why no meaningful response was found.', 'Free text', NULL
UNION ALL
SELECT 4, 'AIAtFault', 'Who bears accountability for the fault. Primary source: worklogs. Fault_Cause and Fault_Cause_Detail are secondary hints only.', 'Controlled', 'Customer | Carrier/Vendor | PCCW | Nobody'
UNION ALL
SELECT 5, 'AIAtFault_Audit', 'One-sentence justification citing the key worklog evidence used for the AIAtFault classification.', 'Free text', NULL
UNION ALL
SELECT 6, 'AIFault_Audit', 'Full audit trail explaining why each AI field was chosen, including AIFaultDomain, AIAtFault, AI_LikelyRootCause, AI_ConfidenceScore, AI_PrimarySymptom, AI_CarrierVendor, and AI_CircuitReference.', 'Free text', NULL
UNION ALL
SELECT 7, 'AI_FaultDomain', 'Technical domain of the fault based on worklogs and device/interface symptoms. Controlled vocabulary: Access, Core, CPE, Power, Security, External, Unknown.', 'Controlled', 'Access | Core | CPE | Power | Security | External | Unknown'
UNION ALL
SELECT 8, 'AI_FaultCause', 'High-level cause category derived from worklogs; use the exact controlled label set defined in HDWL_AIInfused.', 'Controlled', 'Planned Maintenance / Change | Partner / Carrier / Far-End | No Fault Found / Untraced | Platform / API / Portal | Unclassified | Commercial / Billing | Provisioning / Configuration | Security / Policy Block | Force Majeure / External Event | Performance / Quality Degradation | Physical Infrastructure / Hardware | Core Network / IP Backbone | International Transport | Access Network / Local Loop | Service Request / Operations | Customer Side (CPE / Internal)'
UNION ALL
SELECT 9, 'AI_FaultCause_Audit', 'One-sentence justification for AI_FaultCause citing strongest worklog evidence, or explicit fallback reason when metadata fallback was used.', 'Free text', NULL
UNION ALL
SELECT 10, 'AI_CarrierVendor', 'Name of carrier, vendor, or operator entity extracted from worklogs. Returns up to 3 comma-separated names. PCCW is also allowed. Returns Unknown only when no entity can be identified.', 'Free text', NULL
UNION ALL
SELECT 11, 'AI_PrimarySymptom', 'Concise description of the main observable fault symptom described in worklogs.', 'Free text', NULL
UNION ALL
SELECT 12, 'AI_LikelyRootCause', 'Technical root cause hypothesis grounded in worklog evidence. Uses confirmed cause if stated; otherwise best inference.', 'Free text', NULL
UNION ALL
SELECT 13, 'AI_ConfidenceScore', 'Confidence score from 0.0 to 1.0 based on worklog evidence quality. Current guidance prefers 1.0, 0.7, 0.5, or 0.2; avoid 0.0.', 'Numeric', '0.0-1.0; 1.0 confirmed, 0.7 strong evidence, 0.5 partial evidence, 0.2 limited evidence'
UNION ALL
SELECT 14, 'AI_EvidenceSummary', 'Single strongest piece of evidence supporting the AI classifications.', 'Free text', NULL
UNION ALL
SELECT 15, 'AI_DeviceName', 'Device names extracted only from the configured regex pattern over worklogs. Null when no regex match is found.', 'Free text', NULL
UNION ALL
SELECT 16, 'AI_CircuitReference', 'Interface IDs, circuit IDs, service references, VLANs, ports, or path information extracted from worklogs. Null when no circuit or path reference is found.', 'Free text', NULL
ORDER BY SortOrder
