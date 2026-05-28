WITH WorkLogEscalation AS (
  SELECT
    IncidentNumber,
    WorkLogType AS EscalationType,
    DetailedDescription AS EscalationDescription,
    WorkLogSubmitterFullName AS EscalationSubmitter,
    CASE WHEN WorkLogType = 'Internal Escalation' THEN IncidentNumber ELSE NULL END AS MgtEscalation,
    CASE WHEN WorkLogType LIKE 'External Escalation%' THEN IncidentNumber ELSE NULL END AS ExternalEscalation
  FROM (
    SELECT
      IncidentNumber,
      WorkLogType,
      DetailedDescription,
      WorkLogSubmitterFullName,
      ROW_NUMBER() OVER (PARTITION BY IncidentNumber ORDER BY WorkLogSubmitDate DESC) AS RowNum
    FROM `pccw-internal-virt-agent-uat.Looker.WorkLog`
    WHERE WorkLogType LIKE '%Escalation%'
  ) WHERE RowNum = 1
),

JIRAFlags AS (
  SELECT *,
    REGEXP_CONTAINS(Links, r'.*AS3491.*') AS IsAS3491,
    REGEXP_CONTAINS(Links, r'.*CCSUP.*') AS IsCCSUP,
    REGEXP_CONTAINS(Links, r'.*CCONB.*') AS IsCCONB,
    REGEXP_CONTAINS(Links, r'.*COPS.*') AS IsCOPS,
    REGEXP_CONTAINS(Links, r'.*SH.*') AS IsSH,
    REGEXP_CONTAINS(Links, r'.*CSCM.*') AS IsCSCM,
    REGEXP_CONTAINS(Links, r'.*SLSUP.*') AS IsSLSUP,
    REGEXP_CONTAINS(Links, r'.*TAC.*') AS IsTAC,
    REGEXP_CONTAINS(Links, r'.*CCAS.*') AS IsCCAS,
    REGEXP_CONTAINS(Key, r'TAC.*') AS KeyTAC,
    REGEXP_CONTAINS(Key, r'CCAS.*') AS KeyCCAS
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.SecondTierModified`
)

SELECT
  hd.Incident_Number AS T1Tickets,
  CASE WHEN IsAS3491 OR IsCCSUP OR IsCCONB OR IsCOPS OR IsSH OR IsCSCM OR IsSLSUP THEN jtt.Links ELSE NULL END AS T3Tickets,
  jtt.Key AS T2Tickets,
  hd.Status, hd.CaseType, hd.Assigned_Group, hd.Prod_ID,
  hd.Fault_Cause, hd.FaultCauseDetail, hd.Closed_Date, hd.Assignee,
  hd.TrueMTTR_mins, hd.Categorization_Tier_1 AS Category,
  hd.Closed_By, hd.Customer_Name,
  jtt.T AS JIRAType, jtt.Created AS JIRACreated, jtt.Summary, jtt.Links,
  TIMESTAMP_DIFF(jtt.Resolved, jtt.Created, MINUTE) / 60 AS JIRALeadTime_hrs,
  jtt.Resolved AS JIRAResolved, jtt.Updated AS JIRAUpdated, jtt.Status AS JIRAStatus,

  CASE
    WHEN jtt.RemedyTicketNumber IS NULL OR jtt.RemedyTicketNumber = ''
      THEN REGEXP_EXTRACT(jtt.Summary, r'INC\d{12}')
    ELSE jtt.RemedyTicketNumber
  END AS JIRARemedyTicketNumber,

  CASE
    WHEN jtt.Key IS NULL AND jtt.Links IS NULL THEN 'Tier 1'
    WHEN IsAS3491 OR IsCCSUP OR IsCCONB OR IsCOPS OR IsSH OR IsCSCM OR IsSLSUP THEN 'Tier 3'
    ELSE 'Tier 2'
  END AS Tier,

  CASE
    WHEN IsAS3491 THEN 'AS3491'
    WHEN IsCCSUP THEN 'CCSUP'
    WHEN IsCCONB THEN 'CCONB'
    WHEN IsCOPS THEN 'COPS'
    WHEN IsSH THEN 'SH'
    WHEN IsCSCM THEN 'CSCM'
    WHEN IsSLSUP THEN 'SLSUP'
    ELSE 'Others'
  END AS T3Type,

  CASE
    WHEN KeyTAC AND NOT IsTAC THEN 'TAC'
    WHEN KeyCCAS AND NOT IsCCAS THEN 'CCAS'
    WHEN IsTAC THEN 'TAC'
    WHEN IsCCAS THEN 'CCAS'
    ELSE NULL
  END AS T2Type,

  CASE WHEN IsAS3491 THEN hd.Incident_Number ELSE NULL END AS AS3491Solved,
  CASE WHEN IsCCSUP THEN hd.Incident_Number ELSE NULL END AS CCSUPSolved,
  CASE WHEN IsCCONB THEN hd.Incident_Number ELSE NULL END AS CCONBSolved,
  CASE WHEN IsCOPS THEN hd.Incident_Number ELSE NULL END AS COPSSolved,
  CASE WHEN IsSH THEN hd.Incident_Number ELSE NULL END AS SHSolved,
  CASE WHEN IsCSCM THEN hd.Incident_Number ELSE NULL END AS CSCMSolved,
  CASE WHEN KeyTAC OR IsTAC THEN hd.Incident_Number ELSE NULL END AS TACSolved,
  CASE WHEN KeyCCAS OR IsCCAS THEN hd.Incident_Number ELSE NULL END AS CCASSolved,

  CASE
    WHEN jtt.Links IS NOT NULL
      AND NOT IsAS3491 AND NOT IsCCSUP AND NOT IsCCONB AND NOT IsCOPS
      AND NOT IsSH AND NOT IsCSCM AND NOT IsSLSUP
      AND NOT KeyTAC AND NOT KeyCCAS
    THEN hd.Incident_Number
    ELSE NULL
  END AS OtherSolved,

  CASE WHEN hd.TrueMTTR_mins <= 240 THEN 'Pass' ELSE 'Fail' END AS MTTRState,
  CASE WHEN jtt.Key IS NULL AND jtt.Links IS NULL THEN hd.Incident_Number ELSE NULL END AS T1SolvedTickets,
  CASE WHEN jtt.Links IS NOT NULL AND NOT IsTAC AND NOT IsCCAS THEN hd.Incident_Number ELSE NULL END AS T3SolvedTickets,
  CASE
    WHEN jtt.Key IS NOT NULL AND jtt.Links IS NULL
      OR jtt.Key IS NOT NULL AND (IsTAC OR IsCCAS)
    THEN hd.Incident_Number
    ELSE NULL
  END AS T2SolvedTickets,

  hd.TrueMTTR_mins / 60 AS TrueMTTR_hrs,
  wle.MgtEscalation,
  wle.ExternalEscalation,
  CASE WHEN jtt.Key IS NOT NULL THEN hd.Incident_Number END AS `Next Tier Escalation`,
  wle.EscalationType, wle.EscalationDescription, wle.EscalationSubmitter

FROM `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd
LEFT JOIN JIRAFlags AS jtt ON hd.Incident_Number = jtt.RemedyTicketNumber
LEFT JOIN WorkLogEscalation AS wle ON hd.Incident_Number = wle.IncidentNumber

WHERE hd.CaseType = 'Incident' AND hd.Status = 'Closed'
ORDER BY hd.Closed_Date DESC
