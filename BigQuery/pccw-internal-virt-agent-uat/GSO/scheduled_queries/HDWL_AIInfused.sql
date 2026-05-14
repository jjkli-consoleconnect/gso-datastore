-- Incremental AI infusion cache refresh for HDWL tickets.
-- Run as a scheduled query (recommended: every 1-4 hours).
-- This script identifies the first meaningful worklog response per ticket.
-- Resource optimization: only scans candidate keys changed since last run.


DECLARE run_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP();

SET @@query_label = "seeds_environment:prod,seeds_product:aiinfused_hdwl,seeds_component:bigquery";

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` (
  Incident_Number STRING NOT NULL,
  PayloadHash STRING NOT NULL,
  AIFirstResponse STRING,
  AIFirstResponseTimestamp TIMESTAMP,
  AIFirstResponse_Audit STRING,
  AIAtFault STRING,
  AIAtFault_Audit STRING,
  AI_FaultDomain STRING,
  AI_CarrierVendor STRING,
  AI_PrimarySymptom STRING,
  AI_LikelyRootCause STRING,
  AI_ConfidenceScore FLOAT64,
  AI_EvidenceSummary STRING,
  AI_DeviceName STRING,
  AI_CircuitReference STRING,
  ClassifiedAt TIMESTAMP NOT NULL,
  ModelName STRING,
  PromptVersion STRING
)
PARTITION BY DATE(ClassifiedAt)
CLUSTER BY Incident_Number;

ALTER TABLE `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
ADD COLUMN IF NOT EXISTS AIAtFault STRING,
ADD COLUMN IF NOT EXISTS AIAtFault_Audit STRING,
ADD COLUMN IF NOT EXISTS AI_FaultDomain STRING,
ADD COLUMN IF NOT EXISTS AI_CarrierVendor STRING,
ADD COLUMN IF NOT EXISTS AI_PrimarySymptom STRING,
ADD COLUMN IF NOT EXISTS AI_LikelyRootCause STRING,
ADD COLUMN IF NOT EXISTS AI_ConfidenceScore FLOAT64,
ADD COLUMN IF NOT EXISTS AI_EvidenceSummary STRING,
ADD COLUMN IF NOT EXISTS AI_DeviceName STRING,
ADD COLUMN IF NOT EXISTS AI_CircuitReference STRING;

ALTER TABLE `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
DROP COLUMN IF EXISTS AI_NextBestAction,
DROP COLUMN IF EXISTS AI_OwnershipNow,
DROP COLUMN IF EXISTS AI_SLABreachRisk,
DROP COLUMN IF EXISTS AI_SuspectedParty,
DROP COLUMN IF EXISTS AI_DeviceInterfaceContext;

MERGE `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` AS target
USING (
  WITH null_fault_cache AS (
    SELECT DISTINCT Incident_Number
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
    WHERE AIAtFault IS NULL
      OR AIAtFault_Audit IS NULL
      OR AI_FaultDomain IS NULL
      OR AI_CarrierVendor IS NULL
      OR AI_PrimarySymptom IS NULL
      OR AI_LikelyRootCause IS NULL
      OR AI_ConfidenceScore IS NULL
      OR AI_EvidenceSummary IS NULL
      OR COALESCE(PromptVersion, '') != 'hdwl-firstresponse-v17-device-circuit-planned'
      OR AI_FaultDomain NOT IN ('Access', 'Core', 'CPE', 'Power', 'Security', 'External', 'Unknown')
  ),
  candidate_keys AS (
    SELECT DISTINCT Incident_Number
    FROM (
      -- Primary path: closed tickets in the last 24 hours
      SELECT h.Incident_Number
      FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
      WHERE h.Incident_Number IS NOT NULL
        AND h.Fault_Cause IS NOT NULL
        AND h.Assigned_Group IN (
          'Bel NOC',
          'Console Connect',
          'FMC',
          'GSOC',
          'ICX',
          'Planned Event Mgt',
          'PHSOC',
          'Soft Switch Management',
          'USNOC',
          'VAS NOC'
        )
        AND h.Status = 'Closed'
        AND h.Closed_Date >= TIMESTAMP_SUB(run_ts, INTERVAL 24 HOUR)

      UNION DISTINCT

      -- Backfill path: re-process existing cache rows with missing AI enrichment fields
      SELECT Incident_Number FROM null_fault_cache
    )
    WHERE Incident_Number IS NOT NULL
  ),
  w_all AS (
    SELECT
      w.Incident_Number,
      COUNT(*) AS WorkLog_Count,
      STRING_AGG(
        CONCAT(
          '[', FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', w.WorkLog_Submit_Date), '] ',
          COALESCE(w.WorkLog_Submitter, 'Unknown'), ' (', COALESCE(w.WorkLog_Type, ''), '):\n',
          SUBSTR(COALESCE(w.ExtractedDescription, ''), 1, 900),
          CASE
            WHEN STRPOS(COALESCE(w.ExtractedDescription, ''), 'Ticket Progress Update') > 0 THEN CONCAT(
              '\n[Progress Section]\n',
              SUBSTR(
                COALESCE(w.ExtractedDescription, ''),
                GREATEST(1, STRPOS(COALESCE(w.ExtractedDescription, ''), 'Ticket Progress Update') - 120),
                1400
              )
            )
            ELSE ''
          END,
          '\n'
        ),
        '---\n'
        ORDER BY w.WorkLog_Submit_Date
      ) AS WorkLogs_Formatted
    FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
    JOIN candidate_keys ck ON ck.Incident_Number = w.Incident_Number
    GROUP BY w.Incident_Number
  ),
  w_device_names AS (
    SELECT
      w.Incident_Number,
      ARRAY_TO_STRING(ARRAY_AGG(DISTINCT device_name ORDER BY device_name), ', ') AS DeviceNamesExtracted
    FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
    JOIN candidate_keys ck ON ck.Incident_Number = w.Incident_Number
    CROSS JOIN UNNEST(
      REGEXP_EXTRACT_ALL(
        COALESCE(w.ExtractedDescription, ''),
        r'[A-Za-z]{2,3}[0-9]{2,3}\.[A-Za-z]{2,3}[0-9]{2,3}'
      )
    ) AS device_name
    GROUP BY w.Incident_Number
  ),
  latest_cache AS (
    SELECT
      Incident_Number,
      PayloadHash,
      AIAtFault,
      AIAtFault_Audit,
      AI_FaultDomain,
      AI_CarrierVendor,
      AI_PrimarySymptom,
      AI_LikelyRootCause,
      AI_ConfidenceScore,
      AI_EvidenceSummary,
      AI_DeviceName,
      AI_CircuitReference,
      ROW_NUMBER() OVER (
        PARTITION BY Incident_Number
        ORDER BY ClassifiedAt DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
    WHERE Incident_Number IN (SELECT Incident_Number FROM candidate_keys)
  ),
  base AS (
    SELECT
      ck.Incident_Number,
      TO_HEX(SHA256(CONCAT(
        CAST(COALESCE(w.WorkLog_Count, 0) AS STRING), '|',
        COALESCE(w.WorkLogs_Formatted, ''), '|',
        COALESCE(dn.DeviceNamesExtracted, ''), '|',
        COALESCE(h.Assigned_Group, ''), '|',
        COALESCE(h.Customer_Name, ''), '|',
        COALESCE(h.Fault_Cause, ''), '|',
        COALESCE(h.FaultCauseDetail, ''), '|',
        'hdwl-firstresponse-v17-device-circuit-planned'
      ))) AS PayloadHash,
      COALESCE(dn.DeviceNamesExtracted, '') AS DeviceNamesExtracted,
      CONCAT(
        'You are analyzing a helpdesk ticket worklog to identify the FIRST MEANINGFUL response to the customer.\n\n',
        'Ticket customer name: ', COALESCE(h.Customer_Name, 'Unknown'), '\n\n',
        'Assigned_Group: ', COALESCE(h.Assigned_Group, 'Unknown'), '\n',
        'Fault_Cause: ', COALESCE(h.Fault_Cause, 'Unknown'), '\n',
        'Fault_Cause_Detail: ', COALESCE(h.FaultCauseDetail, 'Unknown'), '\n\n',
        'If Assigned_Group = Planned Event Mgt, assume this is most likely planned maintenance or change work unless the worklogs clearly show an unexpected fault.\n',
        'For Planned Event Mgt tickets, maintenance advisories, maintenance progress notices, change execution updates, and maintenance completion notices count as meaningful customer-facing responses when they contain substantive schedule, impact, progress, or completion details.\n',
        'For Planned Event Mgt tickets, prefer AIAtFault = Nobody for planned work unless the worklogs clearly show PCCW caused an unplanned fault or a named external carrier/vendor caused the impact.\n',
        'For Planned Event Mgt tickets, AI_LikelyRootCause may describe scheduled maintenance, planned change, migration, or implementation activity if that is what the worklogs show.\n\n',
        'Only evaluate these customer-facing worklog types:\n',
        '- Email-Progress Update\n',
        '- Internal Work Log (Email)\n',
        'Ignore all other worklog types.\n\n',
        'Determine whether a worklog is truly customer-facing by checking recipient/salutation/body context against the customer.\n',
        'Use the customer name above as a primary anchor, but also allow named customer contacts or generic customer salutations like "Dear Customer".\n',
        'If the message is addressed to a vendor, provider, peering partner, carrier, internal operations team, escalation mailbox, or asks those parties to investigate/review/advice, then it is NOT customer communication and must be ignored.\n',
        'Examples of non-customer messages include vendor escalations like "Hello Tata", "Dear USNOC", or emails to provider/partner mailboxes asking them to check/review logs.\n\n',
        'A MEANINGFUL response is one that:\n',
        '- Provides a substantive update, investigation finding, or action taken\n',
        '- Gives the customer real information about what is happening with their issue\n\n',
        'Also treat as meaningful:\n',
        '- Agent asks targeted troubleshooting questions to the customer (e.g. current situation, ping test result, traceroute, specific validation checks), because this is active customer communication and troubleshooting in progress.\n\n',
        'A NON-MEANINGFUL response is one that ONLY:\n',
        '- Acknowledges receipt (e.g. "We have received your ticket", "Ticket acknowledged")\n',
        '- States the team is looking into it with no further detail\n',
        '- Is a generic auto-response or templated acknowledgement\n',
        '- Simply shares a ticket/incident number with the customer (e.g. "Your incident has been created, reference INC0012345"), with no further context or update\n',
        '- Confirms that a new ticket has been created and a support engineer assigned, even if addressed to the customer and including a ticket reference (e.g. "PCCW Global has created a ticket for you. New Ticket. Reference INC0012345. A support engineer has been assigned.") â€” this is a ticket creation notification only, and is NON-MEANINGFUL.\n\n',
        'Hard exclusion rule:\n',
        '- If WorkLog_Type = "Testing Result Information", treat it as internal-only and NEVER consider it a customer update, even if content appears detailed.\n\n',
        'From the worklogs below, identify the FIRST worklog entry that qualifies as a meaningful response.\n',
        'Return the following:\n',
        '- AIFirstResponse: the exact text of that worklog entry (truncated to 500 chars if needed)\n',
        '- AIFirstResponseTimestamp: the timestamp in ISO 8601 format (e.g. 2025-04-01T09:30:00Z)\n',
        '- AIFirstResponse_Audit: one sentence (max 200 chars) explaining why this entry was chosen as the first meaningful response.\n',
        '  If no meaningful response exists in the worklogs, set AIFirstResponse and AIFirstResponseTimestamp to null,\n',
        '  and set AIFirstResponse_Audit to explain why using one of these true reasons:\n',
        '  - "All customer-facing worklogs are acknowledgements only"\n',
        '  - "No customer communication found in this ticket"\n',
        '  IMPORTANT: if the message only shares incident/ticket number creation/reference with no substantive update,\n',
        '  this is NON-MEANINGFUL and you MUST return AIFirstResponse = null and AIFirstResponseTimestamp = null.\n\n',
        'Also determine AIAtFault using ONLY one label from this fixed set:\n',
        '- Customer\n',
        '- Carrier/Vendor\n',
        '- PCCW\n',
        '- Nobody\n\n',
        'AIAtFault decision rules:\n',
        '- Use Fault_Cause and Fault_Cause_Detail as primary technical evidence.\n',
        '- Use worklog content as supporting context, including interactions with customer, vendor, carrier, and PCCW teams.\n',
        '- Choose Customer when root cause points to customer equipment, customer configuration, customer internal IT, or customer action/inaction.\n',
        '- Choose Carrier/Vendor when root cause points to partner network, far-end fault, peering partner, provider/carrier issue, third-party infrastructure, or vendor platform.\n',
        '- Choose PCCW when root cause points to PCCW network/platform/provisioning/process/configuration/operations mistakes or internal infrastructure faults.\n',
        '- Choose Nobody when evidence indicates no fault found, right-when-tested, force majeure, uncontrollable events, planned maintenance with no clear accountable party, or insufficient evidence to assign blame confidently.\n',
        '- Output must be exactly one of: Customer, Carrier/Vendor, PCCW, Nobody.\n',
        '- Also return AIAtFault_Audit: one sentence (max 200 chars) justifying your classification, citing the key evidence used (e.g. fault cause, worklog detail).\n\n',
        'Also return these enrichment fields derived PRIMARILY from the worklog content below.\n',
        'The worklogs contain all technical communications: internal engineer notes, carrier escalations,\n',
        'vendor responses, testing results, and customer emails. Read them carefully before answering.\n',
        'Fault_Cause and Fault_Cause_Detail are secondary hints only — trust worklog evidence over metadata.\n\n',
        '- AI_FaultDomain: choose EXACTLY ONE label from this fixed set only:\n',
        '  Access (last-mile, access port, DSL, optical access), Core (backbone, routing, switching, IP/MPLS),\n',
        '  CPE (customer premises equipment, router, ONT, NTU), Power (power failure, UPS, generator),\n',
        '  Security (DDoS, BGP hijack, firewall), External (carrier/provider/peering partner fault outside PCCW),\n',
        '  Unknown (insufficient evidence).\n',
        '  Do NOT output free text or combined labels in this field.\n',
        '  Base this on device names, interfaces, symptoms, and what the internal/carrier worklogs say.\n',
        '- AI_CarrierVendor: extract involved carrier/vendor company name(s) from worklogs.\n',
        '  Return telco/provider/vendor entity names only (comma-separated if multiple, max 3 names). PCCW is also an allowed value when PCCW is the relevant network/operator entity referenced in the worklogs.\n',
        '  Examples: "Tata Communications", "NTT", "HKT", "China Telecom", "AT&T", "PCCW".\n',
        '  Look hard for carrier/vendor names in salutations, recipient mailboxes, signatures, domains, quoted emails, escalation targets, subject lines, and internal notes.\n',
        '  Normalize obvious variants and aliases (e.g. "TATA" -> "Tata Communications", "PCCWG" -> "PCCW").\n',
        '  Only return "Unknown" when no carrier/vendor/operator entity is named or can be inferred from the worklogs.\n',
        '- AI_PrimarySymptom: concise description (max 150 chars) of the main symptom observed.\n',
        '  E.g. "complete loss of BGP session", "high packet loss on customer port", "intermittent flaps".\n',
        '  Read what engineers and customers described as the observable fault.\n',
        '- AI_LikelyRootCause: concise technical root cause hypothesis (max 200 chars) grounded in evidence.\n',
        '  E.g. "fiber cut on access segment", "BGP misconfiguration by carrier", "power failure at remote site".\n',
        '  If root cause was confirmed in worklogs, use that. If not, use best evidence.\n',
        '- AI_ConfidenceScore: numeric 0.0 to 1.0 reflecting how certain you are based on evidence quality.\n',
        '  1.0 = explicitly confirmed in worklogs. 0.5 = inferred from partial evidence. 0.2 = very limited info.\n',
        '- AI_EvidenceSummary: one sentence (max 200 chars) citing the single strongest piece of evidence.\n',
        '  Quote key worklog phrases or data points that most support your classification.\n',
        '- AI_CircuitReference: interface IDs, circuit IDs, service references, path references, VLANs, ports, or routing path details (max 300 chars).\n',
        '  Do not return device names in this field unless needed as part of the circuit/path reference.\n',
        '  If no valid circuit/interface/path reference exists, return null.\n',
        '  Regex-extracted device-name candidates from worklogs for separate AI_DeviceName field: ', COALESCE(dn.DeviceNamesExtracted, 'None'), '\n\n',
        'Worklogs (chronological order):\n',
        COALESCE(w.WorkLogs_Formatted, 'No worklogs for this ticket')
      ) AS PromptText
    FROM candidate_keys ck
    LEFT JOIN `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
      ON h.Incident_Number = ck.Incident_Number
    LEFT JOIN w_all w ON w.Incident_Number = ck.Incident_Number
    LEFT JOIN w_device_names dn ON dn.Incident_Number = ck.Incident_Number
  ),
  delta AS (
    SELECT b.*
    FROM base b
    LEFT JOIN latest_cache lc
      ON lc.Incident_Number = b.Incident_Number
     AND lc.rn = 1
    WHERE lc.Incident_Number IS NULL
      OR lc.PayloadHash != b.PayloadHash
      OR lc.AIAtFault IS NULL
      OR lc.AIAtFault_Audit IS NULL
      OR lc.AI_FaultDomain IS NULL
      OR lc.AI_CarrierVendor IS NULL
      OR lc.AI_PrimarySymptom IS NULL
      OR lc.AI_LikelyRootCause IS NULL
      OR lc.AI_ConfidenceScore IS NULL
      OR lc.AI_EvidenceSummary IS NULL
  )
  SELECT
    d.Incident_Number,
    d.PayloadHash,
    CASE
      WHEN REGEXP_CONTAINS(
        LOWER(COALESCE(ai.AIFirstResponse_Audit, '')),
        r'all customer.facing worklogs are acknowledgements only|no customer communication found|no customer-facing email worklogs found|no meaningful response'
      )
      OR REGEXP_CONTAINS(
        LOWER(COALESCE(ai.AIFirstResponse, '')),
        r'please refer to ticket|please refer to inc|incident has been created|ticket has been created|reference inc|has created a ticket for|new ticket'
      )
      THEN NULL
      ELSE ai.AIFirstResponse
    END AS AIFirstResponse,
    CASE
      WHEN REGEXP_CONTAINS(
        LOWER(COALESCE(ai.AIFirstResponse_Audit, '')),
        r'all customer.facing worklogs are acknowledgements only|no customer communication found|no customer-facing email worklogs found|no meaningful response'
      )
      OR REGEXP_CONTAINS(
        LOWER(COALESCE(ai.AIFirstResponse, '')),
        r'please refer to ticket|please refer to inc|incident has been created|ticket has been created|reference inc|has created a ticket for|new ticket'
      )
      THEN NULL
      ELSE SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', ai.AIFirstResponseTimestamp)
    END AS AIFirstResponseTimestamp,
    ai.AIFirstResponse_Audit,
    CASE
      WHEN LOWER(TRIM(COALESCE(ai.AIAtFault, ''))) IN ('customer') THEN 'Customer'
      WHEN LOWER(TRIM(COALESCE(ai.AIAtFault, ''))) IN ('carrier/vendor', 'carrier', 'vendor', 'carrier vendor') THEN 'Carrier/Vendor'
      WHEN LOWER(TRIM(COALESCE(ai.AIAtFault, ''))) IN ('pccw') THEN 'PCCW'
      WHEN LOWER(TRIM(COALESCE(ai.AIAtFault, ''))) IN ('nobody', 'none', 'no one', 'noone', 'not attributable') THEN 'Nobody'
      ELSE 'Nobody'
    END AS AIAtFault,
    ai.AIAtFault_Audit,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'access|last.?mile|local loop|dsl|fttx|pon|olt|ont port') THEN 'Access'
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'core|backbone|mpls|ip routing|router core|switching core|bgp core') THEN 'Core'
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'cpe|customer premise|customer premises|customer router|onu|ont|ntu') THEN 'CPE'
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'power|ups|generator|electric|electricity|power outage') THEN 'Power'
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'security|ddos|attack|hijack|firewall|acl block|geo block') THEN 'Security'
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_FaultDomain, ''))), r'external|carrier|vendor|provider|partner|peering|upstream|far.?end|third.?party') THEN 'External'
      ELSE 'Unknown'
    END AS AI_FaultDomain,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(TRIM(COALESCE(ai.AI_CarrierVendor, ''))), r'^pccw(\s+global|g)?$') THEN 'PCCW'
      ELSE COALESCE(NULLIF(SUBSTR(TRIM(COALESCE(ai.AI_CarrierVendor, '')), 1, 200), ''), 'Unknown')
    END AS AI_CarrierVendor,
    NULLIF(SUBSTR(TRIM(COALESCE(ai.AI_PrimarySymptom, '')), 1, 300), '') AS AI_PrimarySymptom,
    NULLIF(SUBSTR(TRIM(COALESCE(ai.AI_LikelyRootCause, '')), 1, 400), '') AS AI_LikelyRootCause,
    GREATEST(0.0, LEAST(1.0, COALESCE(ai.AI_ConfidenceScore, 0.5))) AS AI_ConfidenceScore,
    NULLIF(SUBSTR(TRIM(COALESCE(ai.AI_EvidenceSummary, '')), 1, 400), '') AS AI_EvidenceSummary,
    NULLIF(SUBSTR(TRIM(COALESCE(d.DeviceNamesExtracted, '')), 1, 500), '') AS AI_DeviceName,
    NULLIF(SUBSTR(TRIM(COALESCE(ai.AI_CircuitReference, '')), 1, 500), '') AS AI_CircuitReference,
    run_ts AS ClassifiedAt,
    'gemini-2.5-flash-via-AI.GENERATE' AS ModelName,
    'hdwl-firstresponse-v17-device-circuit-planned' AS PromptVersion
  FROM (
    SELECT
      d.Incident_Number,
      d.PayloadHash,
      d.DeviceNamesExtracted,
      AI.GENERATE(
        d.PromptText,
        output_schema => '''
          AIFirstResponse STRING OPTIONS(description="Exact text of first meaningful worklog response, or null"),
          AIFirstResponseTimestamp STRING OPTIONS(description="ISO 8601 timestamp of that worklog, or null"),
          AIFirstResponse_Audit STRING OPTIONS(description="One sentence max 200 chars explaining derivation"),
          AIAtFault STRING OPTIONS(description="One value only: Customer, Carrier/Vendor, PCCW, or Nobody"),
          AIAtFault_Audit STRING OPTIONS(description="One sentence max 200 chars justifying the AIAtFault classification"),
          AI_FaultDomain STRING OPTIONS(description="One value only: Access, Core, CPE, Power, Security, External, Unknown"),
          AI_CarrierVendor STRING OPTIONS(description="Carrier/vendor company name(s) from worklogs, comma-separated max 3, or Unknown"),
          AI_PrimarySymptom STRING OPTIONS(description="Primary observed symptom"),
          AI_LikelyRootCause STRING OPTIONS(description="Most likely technical root cause"),
          AI_ConfidenceScore FLOAT64 OPTIONS(description="Confidence score between 0 and 1"),
          AI_EvidenceSummary STRING OPTIONS(description="One sentence citing strongest worklog evidence"),
          AI_CircuitReference STRING OPTIONS(description="Interface IDs, circuit IDs, service references, VLANs, ports, or path details extracted from worklogs")
        ''',
        model_params => JSON '{"generation_config":{"thinking_config": {"thinking_budget": 0}}}'
      ) AS ai
    FROM delta d
  ) d
) AS src
ON target.Incident_Number = src.Incident_Number
WHEN MATCHED THEN UPDATE SET
  target.PayloadHash = src.PayloadHash,
  target.AIFirstResponse = src.AIFirstResponse,
  target.AIFirstResponseTimestamp = src.AIFirstResponseTimestamp,
  target.AIFirstResponse_Audit = src.AIFirstResponse_Audit,
  target.AIAtFault = src.AIAtFault,
  target.AIAtFault_Audit = src.AIAtFault_Audit,
  target.AI_FaultDomain = src.AI_FaultDomain,
  target.AI_CarrierVendor = src.AI_CarrierVendor,
  target.AI_PrimarySymptom = src.AI_PrimarySymptom,
  target.AI_LikelyRootCause = src.AI_LikelyRootCause,
  target.AI_ConfidenceScore = src.AI_ConfidenceScore,
  target.AI_EvidenceSummary = src.AI_EvidenceSummary,
  target.AI_DeviceName = src.AI_DeviceName,
  target.AI_CircuitReference = src.AI_CircuitReference,
  target.ClassifiedAt = src.ClassifiedAt,
  target.ModelName = src.ModelName,
  target.PromptVersion = src.PromptVersion
WHEN NOT MATCHED THEN INSERT (
  Incident_Number,
  PayloadHash,
  AIFirstResponse,
  AIFirstResponseTimestamp,
  AIFirstResponse_Audit,
  AIAtFault,
  AIAtFault_Audit,
  AI_FaultDomain,
  AI_CarrierVendor,
  AI_PrimarySymptom,
  AI_LikelyRootCause,
  AI_ConfidenceScore,
  AI_EvidenceSummary,
  AI_DeviceName,
  AI_CircuitReference,
  ClassifiedAt,
  ModelName,
  PromptVersion
) VALUES (
  src.Incident_Number,
  src.PayloadHash,
  src.AIFirstResponse,
  src.AIFirstResponseTimestamp,
  src.AIFirstResponse_Audit,
  src.AIAtFault,
  src.AIAtFault_Audit,
  src.AI_FaultDomain,
  src.AI_CarrierVendor,
  src.AI_PrimarySymptom,
  src.AI_LikelyRootCause,
  src.AI_ConfidenceScore,
  src.AI_EvidenceSummary,
  src.AI_DeviceName,
  src.AI_CircuitReference,
  src.ClassifiedAt,
  src.ModelName,
  src.PromptVersion
);
