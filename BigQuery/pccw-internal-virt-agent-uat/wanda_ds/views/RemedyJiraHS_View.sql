WITH LatestAI AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT src.*, ROW_NUMBER() OVER (PARTITION BY src.Incident_Number ORDER BY src.ClassifiedAt DESC) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused` AS src
  ) WHERE rn = 1
),
OptimizedWorklog AS (
  SELECT
    worklog.Incident_Number,
    ANY_VALUE(worklog.ExtractedDescription) AS ExtractedDescription,
    ARRAY_AGG(DISTINCT ref.shorthand IGNORE NULLS ORDER BY ref.shorthand) AS Device_Names
  FROM
    `pccw-internal-virt-agent-uat.wanda_ds.RemedyWorkLog` AS worklog
  LEFT JOIN
    `pccw-internal-virt-agent-uat.wanda_ds.device_name_reference` AS ref
  ON
    ref.is_active
    AND ref.shorthand IN UNNEST(
      REGEXP_EXTRACT_ALL(
        LOWER(worklog.ExtractedDescription),
        r'(?i)(?:^|[^a-z0-9])([a-z]{2,7}[0-9]{2,3}[.][a-z]{3}[0-9]{2})(?:[.]pccwbtn[.]net)?(?:$|[^a-z0-9.])'
      )
    )
  GROUP BY
    worklog.Incident_Number
)
SELECT
  remedy_jira.*, 
  worklog.Device_Names,
  worklog.ExtractedDescription,
  latest_ai.AIFault_Audit, latest_ai.AI_FaultCause, latest_ai.AI_FaultCause_Audit,                                         
  hs_scn AS HubSpotSCN,                       
  hs_remedy AS HubSpotRemedyClosure           
FROM
  `pccw-internal-virt-agent-uat.wanda_ds.RemedyJira` AS remedy_jira
LEFT JOIN
  OptimizedWorklog AS worklog ON remedy_jira.Incident_Number = worklog.Incident_Number
LEFT JOIN
  LatestAI AS latest_ai ON remedy_jira.Incident_Number = latest_ai.Incident_Number
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.HubspotSCNFeedbackAgg` AS hs_scn ON remedy_jira.SRNo = hs_scn.srno
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.HubspotRemedyClosureSurveyAgg` AS hs_remedy ON remedy_jira.Incident_Number = hs_remedy.Incident_Number
