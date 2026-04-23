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
        AND h.LastModifiedDate >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)

      UNION DISTINCT

      SELECT w.Incident_Number
      FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
      WHERE w.Incident_Number IS NOT NULL
        AND w.Last_Modified_Date >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)
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
          SUBSTR(COALESCE(w.ExtractedDescription, ''), 1, 600), '\n'
        ),
        '---\n'
        ORDER BY w.WorkLog_Submit_Date
      ) AS WorkLogs_Formatted
    FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
    JOIN candidate_keys ck ON ck.Incident_Number = w.Incident_Number
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
        COALESCE(w.WorkLogs_Formatted, '')
      ))) AS PayloadHash,
      CONCAT(
        'You are analyzing a helpdesk ticket worklog to identify the FIRST MEANINGFUL response to the customer.\n\n',
        'A MEANINGFUL response is one that:\n',
        '- Provides a substantive update, investigation finding, or action taken\n',
        '- Gives the customer real information about what is happening with their issue\n\n',
        'A NON-MEANINGFUL response is one that ONLY:\n',
        '- Acknowledges receipt (e.g. "We have received your ticket", "Ticket acknowledged")\n',
        '- States the team is looking into it with no further detail\n',
        '- Is a generic auto-response or templated acknowledgement\n\n',
        'From the worklogs below, identify the FIRST worklog entry that qualifies as a meaningful response.\n',
        'Return the following:\n',
        '- AIFirstResponse: the exact text of that worklog entry (truncated to 500 chars if needed)\n',
        '- AIFirstResponseTimestamp: the timestamp in ISO 8601 format (e.g. 2025-04-01T09:30:00Z)\n',
        '- AIFirstResponse_Audit: one sentence (max 200 chars) explaining why this entry was chosen as the first meaningful response.\n',
        '  If no meaningful response exists in the worklogs, set AIFirstResponse and AIFirstResponseTimestamp to null,\n',
        '  and set AIFirstResponse_Audit to explain why (e.g. "All worklogs are acknowledgements only").\n\n',
        'Worklogs (chronological order):\n',
        COALESCE(w.WorkLogs_Formatted, 'No worklogs for this ticket')
      ) AS PromptText
    FROM candidate_keys ck
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
    ai.AIFirstResponse,
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', ai.AIFirstResponseTimestamp) AS AIFirstResponseTimestamp,
    ai.AIFirstResponse_Audit,
    run_ts AS ClassifiedAt,
    'gemini-2.5-flash-via-AI.GENERATE' AS ModelName,
    'hdwl-firstresponse-v1' AS PromptVersion
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
