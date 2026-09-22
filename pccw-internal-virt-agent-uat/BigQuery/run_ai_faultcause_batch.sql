DECLARE run_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP();

-- Recent PHSOC incidents (last 24h), up to 10
WITH candidate_keys AS (
  SELECT Incident_Number
  FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`
  WHERE Assigned_Group = 'PHSOC'
    AND CaseType = 'Incident'
    AND Status = 'Closed'
    AND Closed_Date >= TIMESTAMP_SUB(run_ts, INTERVAL 24 HOUR)
  ORDER BY Closed_Date DESC
  LIMIT 10
),

w_all AS (
  SELECT
    w.Incident_Number,
    COUNT(*) AS WorkLog_Count,
    STRING_AGG(
      CONCAT(
        '[', FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', w.WorkLog_Submit_Date), '] ',
        COALESCE(w.WorkLog_Submitter,'Unknown'),' (',COALESCE(w.WorkLog_Type,''),'):\n',
        SUBSTR(COALESCE(w.ExtractedDescription,''),1,900),
        '\n'
      ),
      '---\n' ORDER BY w.WorkLog_Submit_Date
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
    REGEXP_EXTRACT_ALL(COALESCE(w.ExtractedDescription, ''), r'[A-Za-z]{2,3}[0-9]{2,3}\.[A-Za-z]{2,3}[0-9]{2,3}')
  ) AS device_name
  GROUP BY w.Incident_Number
),

h AS (
  SELECT Incident_Number, Assigned_Group, Customer_Name, Fault_Cause, FaultCauseDetail
  FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`
  WHERE Incident_Number IN (SELECT Incident_Number FROM candidate_keys)
)

SELECT
  b.Incident_Number,
  b.PayloadHash,
  b.WorkLogs_Formatted,
  b.Fault_Cause,
  AI.GENERATE(
    b.PromptText,
    output_schema => '''
      AI_FaultCause STRING,
      AIFirstResponse STRING,
      AIFirstResponseTimestamp STRING,
      AI_ConfidenceScore FLOAT64
    ''',
    model_params => JSON '{"generation_config":{"thinking_config": {"thinking_budget": 0}}}'
  ) AS ai_result
FROM (
  SELECT
    ck.Incident_Number,
    TO_HEX(SHA256(CONCAT(
      CAST(COALESCE(w.WorkLog_Count,0) AS STRING),'|',
      COALESCE(w.WorkLogs_Formatted,''),'|',
      COALESCE(dn.DeviceNamesExtracted,''),'|',
      COALESCE(h.Assigned_Group,''),'|',
      COALESCE(h.Customer_Name,''),'|',
      COALESCE(h.Fault_Cause,''),'|',
      COALESCE(h.FaultCauseDetail,''),'|',
      'hdwl-firstresponse-v18-worklog-first-nff-minimize'
    ))) AS PayloadHash,
    COALESCE(w.WorkLogs_Formatted,'') AS WorkLogs_Formatted,
    COALESCE(h.Fault_Cause,'') AS Fault_Cause,
    CONCAT(
      'You are analyzing a helpdesk ticket worklog to identify the FIRST MEANINGFUL response to the customer.\n\n',
      'Ticket customer name: ', COALESCE(h.Customer_Name,'Unknown'), '\n\n',
      'Assigned_Group: ', COALESCE(h.Assigned_Group,'Unknown'), '\n',
      'Fault_Cause: ', COALESCE(h.Fault_Cause,'Unknown'), '\n\n',
      'Also determine AI_FaultCause. Return exactly one label from this list (use exact text):\n',
      '- Planned Maintenance / Change\n',
      '- Partner / Carrier / Far-End\n',
      '- No Fault Found / Untraced\n',
      '- Platform / API / Portal\n',
      '- Unclassified\n',
      '- Commercial / Billing\n',
      '- Provisioning / Configuration\n',
      '- Security / Policy Block\n',
      '- Force Majeure / External Event\n',
      '- Performance / Quality Degradation\n',
      '- Physical Infrastructure / Hardware\n',
      '- Core Network / IP Backbone\n',
      '- International Transport\n',
      '- Access Network / Local Loop\n',
      '- Service Request / Operations\n',
      '- Customer Side (CPE / Internal)\n\n',
      'Choose AI_FaultCause by analyzing worklog content only. If worklogs contain no meaningful customer-facing entries, you may use the ticket Fault_Cause metadata as a fallback, but prefer worklogs whenever available. ONLY return one of the labels above — do NOT invent or return free text. If uncertain, return Unclassified.\n\n',
      'Worklogs (chronological order):\n',
      COALESCE(w.WorkLogs_Formatted,'No worklogs for this ticket')
    ) AS PromptText
  FROM candidate_keys ck
  LEFT JOIN w_all w ON w.Incident_Number = ck.Incident_Number
  LEFT JOIN w_device_names dn ON dn.Incident_Number = ck.Incident_Number
  LEFT JOIN h ON h.Incident_Number = ck.Incident_Number
) b
ORDER BY b.Incident_Number;
