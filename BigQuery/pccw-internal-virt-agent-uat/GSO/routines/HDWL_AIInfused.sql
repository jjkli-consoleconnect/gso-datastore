-- Incremental AI infusion cache refresh for HDWL tickets.
-- Run as a scheduled query (recommended: every 1-4 hours).
-- This script identifies the first meaningful worklog response per ticket.
-- Resource optimization: only scans candidate keys changed since last run.

DECLARE run_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE watermark_ts TIMESTAMP DEFAULT COALESCE(
  (
    SELECT MAX(ClassifiedAt)
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
  ),
  TIMESTAMP_SUB(run_ts, INTERVAL 30 DAY)
);

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` (
  Incident_Number STRING NOT NULL,
  PayloadHash STRING NOT NULL,
  AIFirstResponse STRING,
  AIFirstResponseTimestamp TIMESTAMP,
  AIFirstResponse_Audit STRING,
  ClassifiedAt TIMESTAMP NOT NULL,
  ModelName STRING,
  PromptVersion STRING
)
PARTITION BY DATE(ClassifiedAt)
CLUSTER BY Incident_Number;

MERGE `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` AS target
USING (
  WITH candidate_keys AS (
    SELECT DISTINCT Incident_Number
    FROM (
      SELECT h.Incident_Number
      FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
      WHERE h.Incident_Number IS NOT NULL
        AND h.Assigned_Group IN (
          'Bel NOC',
          'Console Connect',
          'FMC',
          'GSOC',
          'ICX',
          'PHSOC',
          'Planned Event Mgt',
          'Soft Switch Management',
          'USNOC',
          'VAS NOC'
        )
        AND (
          h.LastModifiedDate >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)
          OR h.Submit_Date >= TIMESTAMP_SUB(run_ts, INTERVAL 30 DAY)
          OR h.ReportedDate >= TIMESTAMP_SUB(run_ts, INTERVAL 30 DAY)
        )

      UNION DISTINCT

      SELECT w.Incident_Number
      FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
      JOIN `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
        ON h.Incident_Number = w.Incident_Number
      WHERE w.Incident_Number IS NOT NULL
        AND h.Assigned_Group IN (
          'Bel NOC',
          'Console Connect',
          'FMC',
          'GSOC',
          'ICX',
          'PHSOC',
          'Planned Event Mgt',
          'Soft Switch Management',
          'USNOC',
          'VAS NOC'
        )
        AND w.WorkLog_Type IN ('Email-Progress Update', 'Internal Work Log (Email)')
        AND (
          w.Last_Modified_Date >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)
          OR w.WorkLog_Submit_Date >= TIMESTAMP_SUB(run_ts, INTERVAL 30 DAY)
        )
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
    WHERE w.WorkLog_Type IN ('Email-Progress Update', 'Internal Work Log (Email)')
    GROUP BY w.Incident_Number
  ),
  latest_cache AS (
    SELECT
      Incident_Number,
      PayloadHash,
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
        COALESCE(h.Customer_Name, ''), '|',
        'hdwl-firstresponse-v9'
      ))) AS PayloadHash,
      CONCAT(
        'You are analyzing a helpdesk ticket worklog to identify the FIRST MEANINGFUL response to the customer.\n\n',
        'Ticket customer name: ', COALESCE(h.Customer_Name, 'Unknown'), '\n\n',
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
        '- Confirms that a new ticket has been created and a support engineer assigned, even if addressed to the customer and including a ticket reference (e.g. "PCCW Global has created a ticket for you. New Ticket. Reference INC0012345. A support engineer has been assigned.") — this is a ticket creation notification only, and is NON-MEANINGFUL.\n\n',
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
        'Worklogs (chronological order):\n',
        COALESCE(w.WorkLogs_Formatted, 'No worklogs for this ticket')
      ) AS PromptText
    FROM candidate_keys ck
    LEFT JOIN `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
      ON h.Incident_Number = ck.Incident_Number
    LEFT JOIN w_all w ON w.Incident_Number = ck.Incident_Number
  ),
  delta AS (
    SELECT b.*
    FROM base b
    LEFT JOIN latest_cache lc
      ON lc.Incident_Number = b.Incident_Number
     AND lc.rn = 1
    WHERE lc.Incident_Number IS NULL OR lc.PayloadHash != b.PayloadHash
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
    run_ts AS ClassifiedAt,
    'gemini-2.5-flash-via-AI.GENERATE' AS ModelName,
    'hdwl-firstresponse-v9' AS PromptVersion
  FROM (
    SELECT
      d.Incident_Number,
      d.PayloadHash,
      AI.GENERATE(
        d.PromptText,
        output_schema => '''
          AIFirstResponse STRING OPTIONS(description="Exact text of first meaningful worklog response, or null"),
          AIFirstResponseTimestamp STRING OPTIONS(description="ISO 8601 timestamp of that worklog, or null"),
          AIFirstResponse_Audit STRING OPTIONS(description="One sentence max 200 chars explaining derivation")
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
  target.ClassifiedAt = src.ClassifiedAt,
  target.ModelName = src.ModelName,
  target.PromptVersion = src.PromptVersion
WHEN NOT MATCHED THEN INSERT (
  Incident_Number,
  PayloadHash,
  AIFirstResponse,
  AIFirstResponseTimestamp,
  AIFirstResponse_Audit,
  ClassifiedAt,
  ModelName,
  PromptVersion
) VALUES (
  src.Incident_Number,
  src.PayloadHash,
  src.AIFirstResponse,
  src.AIFirstResponseTimestamp,
  src.AIFirstResponse_Audit,
  src.ClassifiedAt,
  src.ModelName,
  src.PromptVersion
);
