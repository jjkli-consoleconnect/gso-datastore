-- RemedyJira: FULL OUTER JOIN of Remedy (T1) and Jira snapshot (T2/T3)

WITH jira_tickets AS (
  SELECT
    T AS Type,
    Project,
    Key,
    Summary,
    Status,
    Created,
    Updated,
    Resolved,
    Reporter,
    Assignee,
    Component,
    RemedyTicketNumber,
    Links,
    SR_Ref,
    SyncTime,
    TimeToFirstResponse_Elapsed,
    TimeToFirstResponse_Goal,
    TimeToFirstResponse_Breached,
    TimeToFirstResponse_Cycles,
    TimeToResolve_Elapsed,
    TimeToResolve_Goal,
    TimeToResolve_Breached,
    TimeToResolve_Cycles,
    TimeToResolution_Elapsed,
    TimeToResolution_Goal,
    TimeToResolution_Breached,
    TimeToResolution_Cycles,
    TimeToApproveNormalChange_Elapsed,
    TimeToApproveNormalChange_Goal,
    TimeToApproveNormalChange_Breached,
    TimeToApproveNormalChange_Cycles,
    ProlongCase_Elapsed,
    ProlongCase_Goal,
    ProlongCase_Breached,
    ProlongCase_Cycles,
    TimeToCloseAfterResolution_Elapsed,
    TimeToCloseAfterResolution_Goal,
    TimeToCloseAfterResolution_Breached,
    TimeToCloseAfterResolution_Cycles,
    AppSupEscalation
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`
  WHERE IsDeleted IS FALSE
),
comments_agg AS (
  SELECT
    Issue_Key,
    COUNT(*) AS Comment_Count,
    MAX(Created) AS Last_Comment_At,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      Visibility_Type,
      Visibility_Value,
      SyncTime,
      InsertedAt
    ) ORDER BY Created) AS Comments,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      Visibility_Type,
      Visibility_Value,
      SyncTime,
      InsertedAt
    ) ORDER BY Created DESC LIMIT 1)[OFFSET(0)] AS Last_Comment
  FROM `pccw-internal-virt-agent-uat.GSO.JiraComments`
  GROUP BY Issue_Key
),
changelog_agg AS (
  SELECT
    Issue_Key,
    COUNT(*) AS Changelog_Count,
    MAX(Transition_Timestamp) AS Last_Transition_At,
    ARRAY_AGG(STRUCT(
      History_ID,
      Transition_Timestamp,
      Transitioned_From,
      Transitioned_To,
      Transitioned_By_Account_ID,
      Transitioned_By_Display_Name,
      SyncTime
    ) ORDER BY Transition_Timestamp) AS Changelog,
    ARRAY_AGG(STRUCT(
      History_ID,
      Transition_Timestamp,
      Transitioned_From,
      Transitioned_To,
      Transitioned_By_Account_ID,
      Transitioned_By_Display_Name,
      SyncTime
    ) ORDER BY Transition_Timestamp DESC LIMIT 1)[OFFSET(0)] AS Last_Change
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog`
  GROUP BY Issue_Key
),
jira_combined AS (
  SELECT
    t.Type,
    t.Project,
    t.Key,
    t.Summary,
    t.Status,
    t.Created,
    t.Updated,
    t.Resolved,
    t.Reporter,
    t.Assignee,
    t.Component,
    ARRAY_TO_STRING(t.Component, ', ') AS Component_Joined,
    t.RemedyTicketNumber,
    ARRAY_TO_STRING(t.RemedyTicketNumber, ', ') AS RemedyTicketNumber_Joined,
    t.Links,
    t.SR_Ref,
    t.SyncTime,
    t.TimeToFirstResponse_Elapsed,
    t.TimeToFirstResponse_Goal,
    t.TimeToFirstResponse_Breached,
    t.TimeToFirstResponse_Cycles,
    t.TimeToResolve_Elapsed,
    t.TimeToResolve_Goal,
    t.TimeToResolve_Breached,
    t.TimeToResolve_Cycles,
    t.TimeToResolution_Elapsed,
    t.TimeToResolution_Goal,
    t.TimeToResolution_Breached,
    t.TimeToResolution_Cycles,
    t.TimeToApproveNormalChange_Elapsed,
    t.TimeToApproveNormalChange_Goal,
    t.TimeToApproveNormalChange_Breached,
    t.TimeToApproveNormalChange_Cycles,
    t.ProlongCase_Elapsed,
    t.ProlongCase_Goal,
    t.ProlongCase_Breached,
    t.ProlongCase_Cycles,
    t.TimeToCloseAfterResolution_Elapsed,
    t.TimeToCloseAfterResolution_Goal,
    t.TimeToCloseAfterResolution_Breached,
    t.TimeToCloseAfterResolution_Cycles,
    t.AppSupEscalation,
    c.Comment_Count,
    c.Last_Comment_At,
    c.Last_Comment.Comment_ID AS Last_Comment_ID,
    c.Last_Comment.Author_Account_ID AS Last_Comment_Author_Account_ID,
    c.Last_Comment.Author_Display_Name AS Last_Comment_Author_Display_Name,
    c.Last_Comment.Created AS Last_Comment_Created,
    c.Last_Comment.Updated AS Last_Comment_Updated,
    c.Last_Comment.Body AS Last_Comment_Body,
    c.Last_Comment.Visibility_Type AS Last_Comment_Visibility_Type,
    c.Last_Comment.Visibility_Value AS Last_Comment_Visibility_Value,
    c.Last_Comment.SyncTime AS Last_Comment_SyncTime,
    c.Last_Comment.InsertedAt AS Last_Comment_InsertedAt,
    c.Comments,
    ch.Changelog_Count,
    ch.Last_Transition_At,
    ch.Last_Change.History_ID AS Last_Change_History_ID,
    ch.Last_Change.Transition_Timestamp AS Last_Change_Transition_Timestamp,
    ch.Last_Change.Transitioned_From AS Last_Change_Transitioned_From,
    ch.Last_Change.Transitioned_To AS Last_Change_Transitioned_To,
    ch.Last_Change.Transitioned_By_Account_ID AS Last_Change_Transitioned_By_Account_ID,
    ch.Last_Change.Transitioned_By_Display_Name AS Last_Change_Transitioned_By_Display_Name,
    ch.Last_Change.SyncTime AS Last_Change_SyncTime,
    ch.Changelog
  FROM jira_tickets t
  LEFT JOIN comments_agg c ON c.Issue_Key = t.Key
  LEFT JOIN changelog_agg ch ON ch.Issue_Key = t.Key
),
FlattenedJira AS (
  SELECT j.*, remedy_incident AS RemedyTicketNumber_flat
  FROM jira_combined j
  LEFT JOIN UNNEST(j.RemedyTicketNumber) AS remedy_incident
),
LatestAI AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      Incident_Number,
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
      ROW_NUMBER() OVER (PARTITION BY Incident_Number ORDER BY ClassifiedAt DESC) AS rn
    FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
  )
  WHERE rn = 1
)

SELECT
  -- All Remedy fields
  hd.* EXCEPT(Product_Family, JoinKey, SRKey, IncidentKey_alpha, IncidentKey_num, IncidentKey_norm),

  -- Remedy-derived aliases
  hd.Status AS hdStatus,
  hd.Assignee AS hdAssignee,
  hd.LastModifiedDate AS LastModifiedDateHD,
  hd.ReportedBy AS ReportedByHD,
  UPPER(REPLACE(hd.Carrier, '"', '')) AS Carrier_Norm,
  CASE 
    WHEN hd.Customer_Name IS NULL THEN UPPER(REPLACE(shr.CustName, '"', ''))
    ELSE UPPER(REPLACE(hd.Customer_Name, '"', ''))
  END AS Customer_Name_Norm,
  UPPER(REPLACE(hd.SRno, '"', '')) AS SRno_Norm,

  -- All Jira fields with safe aliases for Status/Assignee
  j.* EXCEPT(Status, Assignee, JoinKey, SRKey, IncidentKey_alpha, IncidentKey_num, IncidentKey_norm),
  j.Status AS JiraStatus,
  j.Assignee AS SecondTierAssignee,

  -- Project code
  REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') AS ProjectCode,

  -- Project group (Service Delivery vs Center Operations)
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') IN ('GSDT','CCPROV') THEN 'Service Delivery'
    ELSE 'Center Operations'
  END AS Team,

  -- GSOTeam: priority 1 = Remedy Assigned Group; priority 2 = Jira ProjectCode (from j.Key)
  CASE
    -- Assigned Group -> Team mappings
    WHEN UPPER(TRIM(hd.Assigned_Group)) IN (
      'ASOC','FMC','GSOC','SOFT SWITCH MANAGEMENT','HKNOC','PHSOC','VAS NOC','USNOC',
      'GSOC TX - US','CONSOLE CONNECT','SES','ICX','PLANNED EVENT MGT','BEL NOC',
      'GSOC TX - HK','GSOC TX - PH','GLOBAL HELPDESK'
  ) THEN 'Center Operations'
  WHEN UPPER(TRIM(hd.Assigned_Group)) = 'IT HELPDESK' THEN 'IT Operations'
  WHEN UPPER(TRIM(hd.Assigned_Group)) = 'QUALITY ASSURANCE' THEN 'Quality Assurance'

    -- Fallback to ProjectCode (extracted from j.Key) -> Team mappings
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('GDA','GTA','GKC','CCAI') THEN 'Automation & Analytics'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('TAC','CCAS','VOICECE','IOTCE','TXCE','SMSCE') THEN 'Customer Engineering'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('MSS') THEN 'Center Operations'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('CCPROV','GSDT') THEN 'Global Service Delivery'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('VIM','VVT') THEN 'Vendor Verification'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('ITOPS','ITHD') THEN 'IT Operations'
    ELSE NULL
  END AS GSOTeam,

  -- Headcount: number of Engineers in StaffListCleaned for this GSOTeam
  se.Engineer_Count AS GSOTeam_Engineer_Count,

  -- Jira ticket URL (set data type to URL in Looker Studio)
  CASE WHEN j.Key IS NOT NULL THEN CONCAT('https://consoleconnect.atlassian.net/browse/', j.Key) ELSE NULL END AS JiraURL,

  -- Remedy ticket URL (set data type to URL in Looker Studio)
  CASE WHEN hd.Incident_Number IS NOT NULL THEN CONCAT('https://pccwg-smartit.onbmc.com/smartit/app/#/incident/displayid/', hd.Incident_Number) ELSE NULL END AS RemedyURL,

  -- Tier 2 project flags
  CASE WHEN STRPOS(j.Key, 'CCAS')    > 0 THEN j.Key ELSE NULL END AS CCAS,
  CASE WHEN STRPOS(j.Key, 'TAC')     > 0 THEN j.Key ELSE NULL END AS TAC,
  CASE WHEN STRPOS(j.Key, 'VOICECE') > 0 THEN j.Key ELSE NULL END AS VOICECE,
  CASE WHEN STRPOS(j.Key, 'IOTCE')   > 0 THEN j.Key ELSE NULL END AS IOTCE,
  CASE WHEN STRPOS(j.Key, 'TXCE')    > 0 THEN j.Key ELSE NULL END AS TXCE,
  CASE WHEN STRPOS(j.Key, 'SMSCE')   > 0 THEN j.Key ELSE NULL END AS SMSCE,

  -- T2-only project keys (no Tier-3 links in Links)
  CASE WHEN STRPOS(j.Key, 'CCAS')   > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS CCAS_T2,
  CASE WHEN STRPOS(j.Key, 'TAC')    > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS TAC_T2,
  CASE WHEN STRPOS(j.Key, 'VOICECE')> 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS VOICECE_T2,
  CASE WHEN STRPOS(j.Key, 'IOTCE')  > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS IOTCE_T2,
  CASE WHEN STRPOS(j.Key, 'TXCE')   > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS TXCE_T2,
  CASE WHEN STRPOS(j.Key, 'SMSCE')  > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SMSCE_T2,

  -- SolvedBy (T2) per-project selectors (return j.Key when in project and no Tier-3 links)
  CASE WHEN STRPOS(j.Key, 'CCAS')    > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedByCCAS,
  CASE WHEN STRPOS(j.Key, 'TAC')     > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedByTAC,
  CASE WHEN STRPOS(j.Key, 'VOICECE') > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedByVOICECE,
  CASE WHEN STRPOS(j.Key, 'IOTCE')   > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedByIOTCE,
  CASE WHEN STRPOS(j.Key, 'TXCE')    > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedByTXCE,
  CASE WHEN STRPOS(j.Key, 'SMSCE')   > 0 AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN j.Key ELSE NULL END AS SolvedBySMSCE,

  -- Combined closed/resolved timestamp: prefer Jira Resolved, else Remedy Closed
  COALESCE(j.Resolved, CAST(hd.Closed_Date AS TIMESTAMP)) AS ClosedDateCombined,

  -- Jira outstanding duration since Created (UTC)
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), DAY)  AS JiraOutstandingDuration_day,
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), HOUR) AS JiraOutstandingDuration_hrs,

  -- Lead time from Jira Created to Resolved (NULL if unresolved)
  TIMESTAMP_DIFF(j.Resolved, j.Created, SECOND) AS LeadTime_secs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(j.Resolved, j.Created, HOUR)   AS LeadTime_hrs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, DAY)    AS LeadTime_days,

  -- Remedy lead time from Submit to Closed (NULL if either is NULL)
  TIMESTAMP_DIFF(CAST(hd.Closed_Date AS TIMESTAMP), CAST(hd.Submit_Date AS TIMESTAMP), HOUR) AS RemedyLeadTime_hrs,

  -- MTTR calculations (normalize minutes from Remedy; use TrueMTTR_mins when MTTR_mins missing)
  CAST(hd.TrueMTTR_mins AS FLOAT64) AS MTTR_mins_value,
  SAFE_DIVIDE(CAST(hd.TrueMTTR_mins AS FLOAT64), 60.0)    AS MTTR_hrs,
  SAFE_DIVIDE(CAST(hd.TrueMTTR_mins AS FLOAT64), 1440.0)  AS MTTR_days,

  -- Pass/fail thresholds: >0 and <=240 mins = pass; <=0 or >240 = fail
  CASE
  WHEN hd.TrueMTTR_mins IS NULL THEN NULL
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) > 0 AND CAST(hd.TrueMTTR_mins AS FLOAT64) <= 240 THEN 'MTTRPassed'
    ELSE 'MTTRFailed'
  END AS MTTRStatus,

  CASE
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) > 0 AND CAST(hd.TrueMTTR_mins AS FLOAT64) <= 240 THEN hd.Incident_Number
    ELSE NULL
  END AS MTTRPassed,

  CASE
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) <= 0 OR CAST(hd.TrueMTTR_mins AS FLOAT64) > 240 THEN hd.Incident_Number
    ELSE NULL
  END AS MTTRFailed,

  CASE
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) > 0 AND CAST(hd.TrueMTTR_mins AS FLOAT64) <= 240 THEN CAST(hd.TrueMTTR_mins AS FLOAT64)
    ELSE NULL
  END AS MTTRPassed_mins,

  CASE
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) <= 0 OR CAST(hd.TrueMTTR_mins AS FLOAT64) > 240 THEN CAST(hd.TrueMTTR_mins AS FLOAT64)
    ELSE NULL
  END AS MTTRFailed_mins,
  SAFE_DIVIDE(
    CASE
  WHEN CAST(hd.TrueMTTR_mins AS FLOAT64) <= 0 OR CAST(hd.TrueMTTR_mins AS FLOAT64) > 240 THEN CAST(hd.TrueMTTR_mins AS FLOAT64)
      ELSE NULL
    END,
    60.0
  ) AS MTTRFailed_hrs,

  -- Escalated by Tier 2 projects (project in Key AND Links references Tier-3 projects)
  CASE WHEN STRPOS(j.Key, 'CCAS') > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_CCAS,
  CASE WHEN STRPOS(j.Key, 'TAC')  > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_TAC,
  CASE WHEN STRPOS(j.Key, 'VOICECE') > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_VOICECE,
  CASE WHEN STRPOS(j.Key, 'IOTCE')   > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_IOTCE,
  CASE WHEN STRPOS(j.Key, 'TXCE') > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_TXCE,
  CASE WHEN STRPOS(j.Key, 'SMSCE') > 0 AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491|CCONB|COPS|CSCM|SH') THEN j.Key ELSE NULL END AS EscalatedBy_SMSCE,

  -- Escalated by T1 (Remedy present, Jira present, exclude specific Jira projects)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND j.Key IS NOT NULL AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
    THEN j.Key ELSE NULL
  END AS EscalatedBy_T1,

  -- T1 Escalated (return Incident_Number when escalated to Jira, excluding GSDT/CCPROV)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND j.Key IS NOT NULL AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
    THEN hd.Incident_Number ELSE NULL
  END AS T1Escalated,

  -- T1 Solved (Remedy ticket solved without a Jira key)
  CASE
    WHEN j.Key IS NULL THEN hd.Incident_Number ELSE NULL
  END AS T1Solved,

  -- T2 Escalated (Remedy escalated to T2 Jira: TAC/CCAS/VOICECE/IOTCE/TXCE/SMSCE; exclude GSDT/CCPROV and any with Tier-3 links)
  CASE
    WHEN hd.Incident_Number IS NOT NULL
     AND (
       STRPOS(j.Key, 'TAC') > 0 OR STRPOS(j.Key, 'CCAS') > 0 OR STRPOS(j.Key, 'VOICECE') > 0 OR STRPOS(j.Key, 'IOTCE') > 0 OR STRPOS(j.Key, 'TXCE') > 0 OR STRPOS(j.Key, 'SMSCE') > 0
     )
     AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
     AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)')
    THEN j.Key
    ELSE NULL
  END AS T2Escalated,

  -- T2 Solved (generic T2 key: in T2 projects, not in excluded projects, and no Tier-3 links)
  CASE
    WHEN (
      STRPOS(j.Key, 'TAC') > 0 OR STRPOS(j.Key, 'CCAS') > 0 OR STRPOS(j.Key, 'VOICECE') > 0 OR STRPOS(j.Key, 'IOTCE') > 0 OR STRPOS(j.Key, 'TXCE') > 0 OR STRPOS(j.Key, 'SMSCE') > 0
    )
    AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
    AND NOT REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)')
    THEN j.Key
    ELSE NULL
  END AS T2Solved,

  -- T3 Solved (T2 project key, not excluded, and has Tier-3 links)
  CASE
    WHEN (
      STRPOS(j.Key, 'TAC') > 0 OR STRPOS(j.Key, 'CCAS') > 0 OR STRPOS(j.Key, 'VOICECE') > 0 OR STRPOS(j.Key, 'IOTCE') > 0 OR STRPOS(j.Key, 'TXCE') > 0 OR STRPOS(j.Key, 'SMSCE') > 0
    )
    AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
    AND REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)')
    THEN j.Key
    ELSE NULL
  END AS T3Solved,

  -- T3 Solved By (return group code if Links contain T3 tag)
  CASE
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491') THEN 'AS3491'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CCONB')  THEN 'CCONB'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'COPS')   THEN 'COPS'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CSCM')   THEN 'CSCM'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'SH')     THEN 'SH'
    ELSE NULL
  END AS T3SolvedBy,

  -- Jira created without Remedy (self-created Jira), excluding specific projects
  CASE
    WHEN j.Key IS NOT NULL AND hd.Incident_Number IS NULL AND NOT REGEXP_CONTAINS(j.Key, r'(GSDT|CCPROV)')
    THEN j.Key ELSE NULL
  END AS JiraSelfCreate,

  -- TicketType classification (aligned with JIRA_HD)
  CASE
    WHEN hd.CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request') THEN CONCAT('Remedy','-', hd.CaseType)
    WHEN hd.CaseType IN ('MCEvent-Child','MCEvent','RPO-Child','RPO','UMW-Child','UMW','CRN-Child','CRN') THEN 'Remedy-Maintenance'
    WHEN j.Type IN ('Incident','Change','Support Request','Ecosystem Health Check','Proactive Alert','Billing Task','Problem','Sustaining Reliability Engineering','Task','Project','Knowledge Management','Regression Testing','Service Request','Assignment','Service Request with Approvals') THEN CONCAT(REGEXP_EXTRACT(j.Key, r'^([A-Z]+)'), '-', j.Type)
    ELSE NULL
  END AS TicketType,

  -- Tier classification
  CASE
    WHEN j.Key IS NULL THEN 'T1'
  WHEN ((STRPOS(j.Key,'CCAS')>0 OR STRPOS(j.Key,'TAC')>0 OR STRPOS(j.Key,'VOICECE')>0 OR STRPOS(j.Key,'IOTCE')>0 OR STRPOS(j.Key,'TXCE')>0 OR STRPOS(j.Key,'SMSCE')>0) AND (STRPOS(j.Links,'AS3491')>0 OR STRPOS(j.Links,'CCONB')>0 OR STRPOS(j.Links,'COPS')>0 OR STRPOS(j.Links,'CSCM')>0 OR STRPOS(j.Links,'SH')>0)) THEN 'T3'
  WHEN ((STRPOS(j.Key,'TAC')>0 OR STRPOS(j.Key,'CCAS')>0 OR STRPOS(j.Key,'VOICECE')>0 OR STRPOS(j.Key,'IOTCE')>0 OR STRPOS(j.Key,'TXCE')>0 OR STRPOS(j.Key,'SMSCE')>0) AND (j.Links IS NULL OR NOT (STRPOS(j.Links,'AS3491')>0 OR STRPOS(j.Links,'CCONB')>0 OR STRPOS(j.Links,'COPS')>0 OR STRPOS(j.Links,'CSCM')>0 OR STRPOS(j.Links,'SH')>0))) THEN 'T2'
    ELSE NULL
  END AS SolvedBy,

  -- Tier Assist (simple tier indicator based on Links and Key)
  CASE
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'(AS3491|CCONB|COPS|CSCM|SH)') THEN 'T3'
    WHEN j.Key IS NULL THEN 'T1'
    WHEN (STRPOS(j.Key, 'TAC') > 0 OR STRPOS(j.Key, 'CCAS') > 0 OR STRPOS(j.Key, 'VOICECE') > 0 OR STRPOS(j.Key, 'IOTCE') > 0 OR STRPOS(j.Key, 'TXCE') > 0 OR STRPOS(j.Key, 'SMSCE') > 0) THEN 'T2'
    ELSE NULL
  END AS TierAssist,

  -- Per-project SolvedBy selectors (return j.Key if Links contain the tag)
  CASE WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491') THEN j.Key ELSE NULL END AS SolvedByAS3491,
  CASE WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CCONB')  THEN j.Key ELSE NULL END AS SolvedByCCONB,
  CASE WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'COPS')   THEN j.Key ELSE NULL END AS SolvedByCOPS,
  CASE WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CSCM')   THEN j.Key ELSE NULL END AS SolvedByCSCM,
  CASE WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'SH')     THEN j.Key ELSE NULL END AS SolvedBySH,

  -- Project classification from Links/Key
  CASE
    WHEN STRPOS(j.Links, 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(j.Links, 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(j.Links, 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(j.Links, 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(j.Links, 'SH') > 0 THEN 'SH'
    WHEN STRPOS(j.Key, 'CCAS') > 0 THEN 'CCAS'
    WHEN STRPOS(j.Key, 'TAC') > 0 THEN 'TAC'
    WHEN STRPOS(j.Key, 'VOICECE') > 0 THEN 'VOICECE'
    WHEN STRPOS(j.Key, 'IOTCE') > 0 THEN 'IOTCE'
    WHEN STRPOS(j.Key, 'TXCE') > 0 THEN 'TXCE'
    WHEN STRPOS(j.Key, 'SMSCE') > 0 THEN 'SMSCE'
    ELSE NULL
  END AS SolvedByProject,

  -- Array of all project prefixes from links, excluding the ticket's own project prefix
  ARRAY(
    SELECT DISTINCT proj
    FROM (
      SELECT REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') AS proj
      FROM UNNEST(SPLIT(COALESCE(j.Links, ''), ',')) AS link
      WHERE
        LOWER(TRIM(link)) != 'none'
        AND TRIM(link) != ''
        AND REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') IS NOT NULL
    )
    WHERE proj != REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^(\w+)-')
  ) AS LinkedProject_Clean,

  -- T1 Solved By classification (prefer T3 by Links, else T2 by Key, else T1)
  CASE
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491') THEN 'T3-AS3491'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CCONB')  THEN 'T3-CCONB'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'COPS')   THEN 'T3-COPS'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CSCM')   THEN 'T3-CSCM'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'SH')     THEN 'T3-SH'
    ELSE CASE
      WHEN STRPOS(j.Key, 'TAC')     > 0 THEN 'T2-TAC'
      WHEN STRPOS(j.Key, 'CCAS')    > 0 THEN 'T2-CCAS'
      WHEN STRPOS(j.Key, 'VOICECE') > 0 THEN 'T2-VOICECE'
      WHEN STRPOS(j.Key, 'IOTCE')   > 0 THEN 'T2-IOTCE'
      WHEN STRPOS(j.Key, 'TXCE')    > 0 THEN 'T2-TXCE'
      WHEN STRPOS(j.Key, 'SMSCE')   > 0 THEN 'T2-SMSCE'
      ELSE 'T1'
    END
  END AS T1SolvedBy,

  -- T2 Solved By (prefer T3 by Links, else T2 by Key; return group code)
  CASE
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'AS3491') THEN 'AS3491'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CCONB')  THEN 'CCONB'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'COPS')   THEN 'COPS'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'CSCM')   THEN 'CSCM'
    WHEN REGEXP_CONTAINS(COALESCE(j.Links, ''), r'SH')     THEN 'SH'
    ELSE CASE
      WHEN STRPOS(j.Key, 'TAC')     > 0 THEN 'TAC'
      WHEN STRPOS(j.Key, 'CCAS')    > 0 THEN 'CCAS'
      WHEN STRPOS(j.Key, 'VOICECE') > 0 THEN 'VOICECE'
      WHEN STRPOS(j.Key, 'IOTCE')   > 0 THEN 'IOTCE'
      WHEN STRPOS(j.Key, 'TXCE')    > 0 THEN 'TXCE'
      WHEN STRPOS(j.Key, 'SMSCE')   > 0 THEN 'SMSCE'
      ELSE NULL
    END
  END AS T2SolvedBy,

  -- Join diagnostics and unified keys
  CASE
  WHEN hd.IncidentKey_norm IS NOT NULL AND j.IncidentKey_norm IS NOT NULL AND hd.IncidentKey_norm = j.IncidentKey_norm THEN 'Incident'
    ELSE NULL
  END AS JoinPath,
  COALESCE(NULLIF(hd.SRno, ''), j.SRKey) AS UnifiedSR,

  -- Product enrichment from SHRPeople (fallbacks)
  CASE WHEN hd.ProductDescription IS NULL THEN CONCAT(shr.`Product ID`, ' ', shr.`ProductDescription`) ELSE hd.ProductDescription END AS ProductID,
  CASE WHEN hd.Product_Family IS NULL THEN shr.`Product Family` ELSE hd.Product_Family END AS Product_Family,

  -- Latest AI enrichment fields
  ai.AIFirstResponse,
  ai.AIFirstResponseTimestamp,
  ai.AIFirstResponse_Audit,
  ai.AIAtFault,
  ai.AIAtFault_Audit,
  ai.AI_FaultDomain,
  ai.AI_CarrierVendor,
  ai.AI_PrimarySymptom,
  ai.AI_LikelyRootCause,
  ai.AI_ConfidenceScore,
  ai.AI_EvidenceSummary,
  ai.AI_DeviceName,
  ai.AI_CircuitReference

FROM (
  SELECT
    hd.*,
    COALESCE(NULLIF(hd.SRno, ''), hd.Incident_Number) AS JoinKey,
    NULLIF(REGEXP_REPLACE(hd.SRno, r'"', ''), '') AS SRKey,
    UPPER(REGEXP_REPLACE(TRIM(hd.Incident_Number), r'[^A-Z0-9]', '')) AS IncidentKey_alpha,
    REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(hd.Incident_Number), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') AS IncidentKey_num,
    COALESCE(
      NULLIF(UPPER(REGEXP_REPLACE(TRIM(hd.Incident_Number), r'[^A-Z0-9]', '')), ''),
      NULLIF(REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(hd.Incident_Number), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', ''), '')
    ) AS IncidentKey_norm
  FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
) AS hd
FULL OUTER JOIN (
  SELECT
    j.*,
    COALESCE(CONCAT('SR', NULLIF(j.SR_Ref, '')), j.RemedyTicketNumber_flat) AS JoinKey,
    CONCAT('SR', NULLIF(j.SR_Ref, '')) AS SRKey,
    UPPER(REGEXP_REPLACE(TRIM(j.RemedyTicketNumber_flat), r'[^A-Z0-9]', '')) AS IncidentKey_alpha,
    REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(j.RemedyTicketNumber_flat), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', '') AS IncidentKey_num,
    COALESCE(
      NULLIF(UPPER(REGEXP_REPLACE(TRIM(j.RemedyTicketNumber_flat), r'[^A-Z0-9]', '')), ''),
      NULLIF(REGEXP_REPLACE(REGEXP_EXTRACT(UPPER(REGEXP_REPLACE(TRIM(j.RemedyTicketNumber_flat), r'[^A-Z0-9]', '')), r'(\d+)'), r'^0+', ''), '')
    ) AS IncidentKey_norm
  FROM FlattenedJira AS j
) AS j
  ON hd.IncidentKey_norm = j.IncidentKey_norm
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS shr
  ON COALESCE(j.SRKey, hd.SRKey) = shr.SRNo
LEFT JOIN LatestAI AS ai
  ON ai.Incident_Number = COALESCE(hd.Incident_Number, j.RemedyTicketNumber_flat)
LEFT JOIN (
  SELECT
    Team_Name,
    COUNTIF(UPPER(Category1) = 'ENGINEER') AS Engineer_Count
  FROM `pccw-internal-virt-agent-uat.GSO.StaffListCleaned`
  GROUP BY Team_Name
) AS se
ON se.Team_Name = (
  CASE
    -- Assigned Group -> Team mappings (priority 1)
    WHEN UPPER(TRIM(hd.Assigned_Group)) IN (
      'ASOC','FMC','GSOC','SOFT SWITCH MANAGEMENT','HKNOC','PHSOC','VAS NOC','USNOC',
      'GSOC TX - US','CONSOLE CONNECT','SES','ICX','PLANNED EVENT MGT','BEL NOC',
      'GSOC TX - HK','GSOC TX - PH','GLOBAL HELPDESK'
    ) THEN 'Center Operations'
    WHEN UPPER(TRIM(hd.Assigned_Group)) = 'IT HELPDESK' THEN 'IT Operations'
    WHEN UPPER(TRIM(hd.Assigned_Group)) = 'QUALITY ASSURANCE' THEN 'Quality Assurance'

    -- Fallback to ProjectCode (priority 2)
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('GDA','GTA','GKC','CCAI') THEN 'Automation & Analytics'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('TAC','CCAS','VOICECE','IOTCE','TXCE','SMSCE') THEN 'Customer Engineering'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('MSS') THEN 'Center Operations'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('CCPROV','GSDT') THEN 'Global Service Delivery'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('VIM','VVT') THEN 'Vendor Verification'
    WHEN REGEXP_EXTRACT(j.Key, r'^([A-Z]+)') IN ('ITOPS','ITHD') THEN 'IT Operations'
    ELSE NULL
  END
)

-- Exclude Jira project keys for automation/analytics/internal projects
WHERE 
  REGEXP_CONTAINS(COALESCE(j.Key, ''), r'(TXCE|GSDT|ITHD|MSS|IOTCE|TAC|VOICECE|CCAS|SMSCE|CCPROV)')
  OR j.Key IS NULL






