WITH LatestAI AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      src.*,
      ROW_NUMBER() OVER (
        PARTITION BY src.Incident_Number
        ORDER BY src.ClassifiedAt DESC
      ) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` AS src
  )
  WHERE rn = 1
)
SELECT
  remedy_jira.*, 
  worklog_devices.Device_Names,
  worklog.ExtractedDescription,
  latest_ai.AIFault_Audit, latest_ai.AI_FaultCause, latest_ai.AI_FaultCause_Audit, -- Dynamic list of non-duplicate AI columns gets injected here
  hs_scn AS HubSpotSCN,                       -- Nested struct of SCN feedback
  hs_remedy AS HubSpotRemedyClosure           -- Nested struct of closure feedback
FROM
  `pccw-internal-virt-agent-uat.wanda_ds.RemedyJira` AS remedy_jira
LEFT JOIN (
  SELECT
    worklog.Incident_Number,
    ARRAY_AGG(DISTINCT ref.shorthand ORDER BY ref.shorthand) AS Device_Names
  FROM
    `pccw-internal-virt-agent-uat.wanda_ds.RemedyWorkLog` AS worklog
  CROSS JOIN
    UNNEST(
      REGEXP_EXTRACT_ALL(
        LOWER(worklog.ExtractedDescription),
        r'(?i)(?:^|[^a-z0-9])([a-z]{2,7}[0-9]{2,3}[.][a-z]{3}[0-9]{2})(?:[.]pccwbtn[.]net)?(?:$|[^a-z0-9.])'
      )
    ) AS device_name_candidate
  JOIN
    `pccw-internal-virt-agent-uat.wanda_ds.device_name_reference` AS ref
  ON
    ref.is_active
    AND ref.shorthand = device_name_candidate
  GROUP BY
    worklog.Incident_Number
) AS worklog_devices
ON
  remedy_jira.Incident_Number = worklog_devices.Incident_Number
LEFT JOIN
  `pccw-internal-virt-agent-uat.wanda_ds.RemedyWorkLog` AS worklog
ON
  remedy_jira.Incident_Number = worklog.Incident_Number
LEFT JOIN
  LatestAI AS latest_ai
ON
  remedy_jira.Incident_Number = latest_ai.Incident_Number
-- JOIN HUBSPOT SCN DATA (Using UAT path)
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.HubspotSCNFeedbackAgg` AS hs_scn
ON
  remedy_jira.SRNo = hs_scn.srno
-- JOIN HUBSPOT REMEDY CLOSURE DATA (Using UAT path)
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.HubspotRemedyClosureSurveyAgg` AS hs_remedy
ON
  remedy_jira.Incident_Number = hs_remedy.Incident_Number
