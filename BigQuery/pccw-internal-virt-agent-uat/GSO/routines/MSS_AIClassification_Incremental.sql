-- Incremental AI classification cache refresh for MSS tickets.
-- Run as a scheduled query (recommended: every 1-4 hours).
-- This script only reclassifies rows when relevant source content changes.
-- Resource optimization: only scan candidate keys changed since last run.

DECLARE run_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE watermark_ts TIMESTAMP DEFAULT COALESCE(
  (
    SELECT MAX(ClassifiedAt)
    FROM `pccw-internal-virt-agent-uat.GSO.MSS_AIClassification`
  ),
  TIMESTAMP_SUB(run_ts, INTERVAL 30 DAY)
);

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.MSS_AIClassification` (
  Key STRING NOT NULL,
  PayloadHash STRING NOT NULL,
  SourceUpdated TIMESTAMP,
  LastCommentAt TIMESTAMP,
  AIRootCause STRING,
  AIResolutionSecurity STRING,
  AISymptoms STRING,
  AIAtFault STRING,
  AIAtFaultAudit STRING,
  ClassifiedAt TIMESTAMP NOT NULL,
  ModelName STRING,
  PromptVersion STRING
)
PARTITION BY DATE(ClassifiedAt)
CLUSTER BY Key;

MERGE `pccw-internal-virt-agent-uat.GSO.MSS_AIClassification` AS target
USING (
  WITH candidate_keys AS (
    SELECT DISTINCT Key
    FROM (
      SELECT jt.Key AS Key
      FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` jt
      WHERE COALESCE(jt.IsDeleted, FALSE) = FALSE
        AND jt.Key IS NOT NULL
        AND (
          COALESCE(jt.Project, '') = 'Managed Security Services'
          OR REGEXP_CONTAINS(COALESCE(jt.Key, ''), r'^MSS-')
        )
        AND jt.Updated >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)

      UNION DISTINCT

      SELECT jc.Issue_Key AS Key
      FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` jc
      WHERE REGEXP_CONTAINS(COALESCE(jc.Issue_Key, ''), r'^MSS-')
        AND jc.Created >= TIMESTAMP_SUB(watermark_ts, INTERVAL 6 HOUR)
    )
    WHERE Key IS NOT NULL
  ),
  t AS (
    SELECT
      jt.Key,
      jt.Summary,
      jt.RootCause,
      jt.ResolutionSecurity,
      jt.Symptoms,
      jt.Updated
    FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` jt
    JOIN candidate_keys ck ON ck.Key = jt.Key
    WHERE COALESCE(jt.IsDeleted, FALSE) = FALSE
      AND jt.Key IS NOT NULL
      AND (
        COALESCE(jt.Project, '') = 'Managed Security Services'
        OR REGEXP_CONTAINS(COALESCE(jt.Key, ''), r'^MSS-')
      )
  ),
  c_last AS (
    SELECT
      jc.Issue_Key,
      ARRAY_AGG(STRUCT(Created, Body) ORDER BY Created DESC LIMIT 1)[OFFSET(0)] AS Last_Comment
    FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` jc
    JOIN candidate_keys ck ON ck.Key = jc.Issue_Key
    WHERE REGEXP_CONTAINS(COALESCE(jc.Issue_Key, ''), r'^MSS-')
    GROUP BY jc.Issue_Key
  ),
  latest_cache AS (
    SELECT
      Key,
      PayloadHash,
      ROW_NUMBER() OVER (
        PARTITION BY Key
        ORDER BY ClassifiedAt DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.MSS_AIClassification`
    WHERE Key IN (SELECT Key FROM candidate_keys)
  ),
  base AS (
    SELECT
      t.Key,
      t.Updated AS SourceUpdated,
      c.Last_Comment.Created AS LastCommentAt,
      TO_HEX(SHA256(CONCAT(
        COALESCE(t.Summary, ''), '|',
        COALESCE(t.RootCause, ''), '|',
        COALESCE(t.ResolutionSecurity, ''), '|',
        COALESCE(t.Symptoms, ''), '|',
        COALESCE(SUBSTR(c.Last_Comment.Body, 1, 1200), '')
      ))) AS PayloadHash,
      CONCAT(
        'You are a managed security operations analyst for a Managed Security Services (MSS) team.\n',
        'Analyze this Jira ticket and classify it using ONLY the fixed category lists below.\n',
        'You must pick the single best matching category for each field. Return null if there is genuinely not enough information.\n\n',
        'AIRootCause - pick exactly one:\n',
        '  "Firewall Policy Misconfiguration"\n',
        '  "SSL/TLS Inspection Issue"\n',
        '  "Security Alert - False Positive"\n',
        '  "Authentication / Access Control Failure"\n',
        '  "Malware / Active Threat Detected"\n',
        '  "Log Source / SIEM Ingestion Issue"\n',
        '  "Network / Routing Issue"\n',
        '  "Security Platform / Tool Defect"\n',
        '  "VPN Connectivity Issue"\n',
        '  "Customer-Initiated Change"\n',
        '  "Vulnerability / Patch Management"\n',
        '  "No Issue Identified"\n\n',
        'AIResolutionSecurity - pick exactly one:\n',
        '  "Policy Exception / Whitelist Added"\n',
        '  "Firewall Policy Created or Modified"\n',
        '  "Security Configuration Adjusted"\n',
        '  "Firmware / Software Upgraded"\n',
        '  "Resolved by Customer"\n',
        '  "No Action Required"\n',
        '  "Service / Process Restarted"\n',
        '  "Resolved by ISP / Third Party"\n',
        '  "Escalated to Vendor"\n',
        '  "Detection / Alert Rule Tuned"\n\n',
        'AISymptoms - pick exactly one:\n',
        '  "Internet / Web Access Blocked"\n',
        '  "VPN / Tunnel Connectivity Failure"\n',
        '  "Authentication / User Access Failure"\n',
        '  "Security Alert Triggered"\n',
        '  "Log Source / Event Ingestion Gap"\n',
        '  "High Resource Usage / Performance Degraded"\n',
        '  "Network Connectivity / Packet Loss"\n',
        '  "Application or Service Blocked"\n',
        '  "Certificate / TLS Error"\n',
        '  "No Observable Symptom"\n\n',
        'AIAtFault - pick exactly one: "PCCW", "Customer", or "None"\n',
        'AIAtFaultAudit - one sentence max 160 chars citing field evidence for AIAtFault.\n\n',
        'Ticket data:\n',
        'Summary: ', COALESCE(t.Summary, ''), '\n',
        'RootCause: ', COALESCE(t.RootCause, ''), '\n',
        'ResolutionSecurity: ', COALESCE(t.ResolutionSecurity, ''), '\n',
        'Symptoms: ', COALESCE(t.Symptoms, ''), '\n',
        'LatestComment: ', COALESCE(SUBSTR(c.Last_Comment.Body, 1, 1200), '')
      ) AS PromptText
    FROM t
    LEFT JOIN c_last c ON c.Issue_Key = t.Key
  ),
  delta AS (
    SELECT
      b.*
    FROM base b
    LEFT JOIN latest_cache lc
      ON lc.Key = b.Key
     AND lc.rn = 1
    WHERE lc.Key IS NULL OR lc.PayloadHash != b.PayloadHash
  )
  SELECT
    d.Key,
    d.PayloadHash,
    d.SourceUpdated,
    d.LastCommentAt,
    ai.AIRootCause,
    ai.AIResolutionSecurity,
    ai.AISymptoms,
    ai.AIAtFault,
    ai.AIAtFaultAudit,
    run_ts AS ClassifiedAt,
    'gemini-2.5-flash-via-AI.GENERATE' AS ModelName,
    'mss-v2-fixed-taxonomy' AS PromptVersion
  FROM (
    SELECT
      d.Key,
      d.PayloadHash,
      d.SourceUpdated,
      d.LastCommentAt,
      AI.GENERATE(
        d.PromptText,
        output_schema => '''
          AIRootCause STRING OPTIONS(description="Root cause category from fixed list"),
          AIResolutionSecurity STRING OPTIONS(description="Resolution category from fixed list"),
          AISymptoms STRING OPTIONS(description="Symptoms category from fixed list"),
          AIAtFault STRING OPTIONS(description="PCCW, Customer, or None"),
          AIAtFaultAudit STRING OPTIONS(description="One sentence max 160 chars")
        ''',
        model_params => JSON '{"generation_config":{"thinking_config": {"thinking_budget": 0}}}'
      ) AS ai
    FROM delta d
  ) d
) AS src
ON target.Key = src.Key
WHEN MATCHED THEN UPDATE SET
  target.PayloadHash = src.PayloadHash,
  target.SourceUpdated = src.SourceUpdated,
  target.LastCommentAt = src.LastCommentAt,
  target.AIRootCause = src.AIRootCause,
  target.AIResolutionSecurity = src.AIResolutionSecurity,
  target.AISymptoms = src.AISymptoms,
  target.AIAtFault = src.AIAtFault,
  target.AIAtFaultAudit = src.AIAtFaultAudit,
  target.ClassifiedAt = src.ClassifiedAt,
  target.ModelName = src.ModelName,
  target.PromptVersion = src.PromptVersion
WHEN NOT MATCHED THEN INSERT (
  Key,
  PayloadHash,
  SourceUpdated,
  LastCommentAt,
  AIRootCause,
  AIResolutionSecurity,
  AISymptoms,
  AIAtFault,
  AIAtFaultAudit,
  ClassifiedAt,
  ModelName,
  PromptVersion
) VALUES (
  src.Key,
  src.PayloadHash,
  src.SourceUpdated,
  src.LastCommentAt,
  src.AIRootCause,
  src.AIResolutionSecurity,
  src.AISymptoms,
  src.AIAtFault,
  src.AIAtFaultAudit,
  src.ClassifiedAt,
  src.ModelName,
  src.PromptVersion
);
