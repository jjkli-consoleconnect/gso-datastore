WITH FlattenedTierTwo AS (
  SELECT
    t.*,
    CASE
      WHEN t.Links IS NULL THEN NULL
      ELSE (
        SELECT STRING_AGG(UPPER(trim_link), ', ')
        FROM (
          SELECT TRIM(link) AS trim_link
          FROM UNNEST(SPLIT(t.Links, ',')) AS link
          WHERE TRIM(link) != '' AND LOWER(TRIM(link)) != 'none'
        )
      )
    END AS Links_clean,
    remedy_incident AS RemedyTicketNumber_flat
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
    LEFT JOIN UNNEST(t.RemedyTicketNumber) AS remedy_incident
  WHERE COALESCE(t.IsDeleted, FALSE) = FALSE
    AND NOT REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAI|GTA|GDA|GKC|OCR|QMS|CSM|GSOSI|SH|VIM|VME)')
),
RankedJira AS (
  -- Deduplicate: per Remedy incident, pick the primary Jira (prioritize T2 projects)
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY RemedyTicketNumber_flat ORDER BY 
      CASE 
        WHEN STRPOS(Key, 'TAC') > 0 THEN 1
        WHEN STRPOS(Key, 'CCAS') > 0 THEN 2
        WHEN STRPOS(Key, 'VOICECE') > 0 THEN 3
        WHEN STRPOS(Key, 'IOTCE') > 0 THEN 4
        WHEN STRPOS(Key, 'TXCE') > 0 THEN 5
        WHEN STRPOS(Key, 'SMSCE') > 0 THEN 6
        ELSE 7
      END,
      Key ASC
    ) AS jira_rank
  FROM FlattenedTierTwo
),
UniqueJira AS (
  -- Final deduplication: ensure each Jira Key appears only once
  -- Priority: 1) Has Remedy link with jira_rank=1, 2) Any Remedy link, 3) No Remedy link
  SELECT *
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY Key ORDER BY 
        CASE WHEN RemedyTicketNumber_flat IS NOT NULL AND jira_rank = 1 THEN 1
             WHEN RemedyTicketNumber_flat IS NOT NULL THEN 2
             ELSE 3
        END,
        RemedyTicketNumber_flat DESC NULLS LAST
      ) AS unique_rank
    FROM RankedJira
    WHERE jira_rank = 1 OR RemedyTicketNumber_flat IS NULL
  )
  WHERE unique_rank = 1
)
SELECT
  hd.Incident_Number,
  hd.Status AS hdStatus,
  hd.CaseType,
  hd.Priority,
  hd.Urgency,
  CASE
    WHEN st.`T` IS NOT NULL THEN (REGEXP_EXTRACT(Key, r'^([A-Z]+)') || '-' || st.`T`)
    WHEN CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request', 'MCEvent-Child', 'MCEvent') THEN ('Remedy-' || CaseType)
    WHEN CaseType IN (
      'RPO-Child', 'RPO', 'UMW-Child', 'UMW', 'CRN-Child', 'CRN'
    ) THEN 'Remedy-Maintenance'
    ELSE NULL
  END AS TicketType,
  hd.Assigned_Group,
  hd.Categorization_Tier_1,
  hd.Categorization_Tier_2,
  hd.Categorization_Tier_3,
  hd.GCSC_1st_Customer_Update,
  hd.GCSC_2nd_Customer_Update,
  hd.GCSC_3rd_Customer_Update,
  hd.Initial_Response_Time,
  hd.Second_Response_Time,
  hd.Third_Response_Time,
  hd.Fault_Cause,
  hd.Closed_Date,
  hd.Submit_Date,
  hd.Assignee AS hdAssignee,
  hd.Closed_By,
  hd.Submitter,
  hd.TrueMTTR_mins,
  hd.Cust_ID,
  -- ClosedDateCombined: Returns Closed_Date if available, otherwise Resolved
  COALESCE(hd.Closed_Date, st.Resolved) AS ClosedDateCombined,
  UPPER(REPLACE(hd.Carrier, '"', '')) AS Carrier,
  CASE 
    WHEN hd.Customer_Name IS NULL THEN UPPER(REPLACE(shr.CustName, '"', ''))
    ELSE UPPER(REPLACE(hd.Customer_Name, '"', ''))
  END AS Customer_Name,
  UPPER(REPLACE(hd.SRno, '"', '')) AS SRno,
  hd.LastResolvedDate,
  hd.ReportedDate,
  hd.RespondedDate,
  hd.FaultCauseDetail,
  hd.LastModifiedDate AS LastModifiedDateHD,
  hd.ReportedBy AS ReportedByHD,
  CASE WHEN hd.Status = 'Assigned' THEN "1-Assigned"
        WHEN hd.Status = 'In Progress' THEN "2-In Progress"
        WHEN hd.Status = 'Pending' THEN "3-Pending"
        WHEN hd.Status = 'Resolved' THEN "4-Resolved"
        WHEN hd.Status = 'Closed' THEN "5-Closed"
        WHEN hd.Status = 'Cancelled' THEN "6-Cancelled"
    ELSE NULL 
  END AS TicketProcess,
  st.T AS Type,
  st.Key,
  st.Summary,
  st.Status AS JiraStatus,
  st.Created,
  st.Updated,
  st.Resolved,
  st.Assignee AS SecondTierAssignee,
  st.RemedyTicketNumber,
  st.Links_clean AS Links,
  REGEXP_EXTRACT(Key, r'^([A-Z]+)') AS ProjectCode,
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('GSDT','CCPROV') THEN 'Service Delivery'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('TAC', 'CCAS', 'IOTCE', 'VOICECE', 'TXCE', 'SMSCE', 'SH') THEN 'Support'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('ITHD', 'ITOPS') THEN 'IT Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IN ('MSS') THEN 'Center Operations'
    WHEN REGEXP_EXTRACT(COALESCE(Key, ''), r'^([A-Z]+)') IS NULL THEN 'Support'
    ELSE 'Other'
  END AS Team,
  -- T1 Escalated: Remedy ticket escalated by T1 (has any Jira key, excluding Service Delivery projects)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN hd.Incident_Number
    ELSE NULL
  END AS T1Escalated,
  
  -- T1 Solved: Remedy ticket solved by T1 (no Jira escalation)
  CASE
    WHEN st.Key IS NULL
    THEN hd.Incident_Number
    ELSE NULL
  END AS T1Solved,
  
  -- T1 Solved By: Determines which tier/project resolved the T1 ticket (multi-level hierarchy)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'T3-AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'T3-CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'T3-COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'T3-CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'T3-SH'
    ELSE 
      CASE 
        WHEN STRPOS(st.Key, 'TAC') > 0 THEN 'T2-TAC'
        WHEN STRPOS(st.Key, 'CCAS') > 0 THEN 'T2-CCAS'
        WHEN STRPOS(st.Key, 'VOICECE') > 0 THEN 'T2-VOICECE'
        WHEN STRPOS(st.Key, 'MSS') > 0 THEN 'T2-MSS'
        WHEN STRPOS(st.Key, 'TXCE') > 0 THEN 'T2-TXCE'
        WHEN STRPOS(st.Key, 'SMSCE') > 0 THEN 'T2-SMSCE'
        WHEN STRPOS(st.Key, 'IOTCE') > 0 THEN 'T2-IOTCE'
        ELSE 'T1'
      END
  END AS T1SolvedBy,
  
  -- T2 Solved By: Determines which tier/project resolved the T2 ticket (when escalated)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
    ELSE 
      CASE 
        WHEN STRPOS(st.Key, 'TAC') > 0 THEN 'TAC'
        WHEN STRPOS(st.Key, 'CCAS') > 0 THEN 'CCAS'
        WHEN STRPOS(st.Key, 'VOICECE') > 0 THEN 'VOICECE'
        WHEN STRPOS(st.Key, 'IOTCE') > 0 THEN 'IOTCE'
        WHEN STRPOS(st.Key, 'TXCE') > 0 THEN 'TXCE'
        WHEN STRPOS(st.Key, 'SMSCE') > 0 THEN 'SMSCE'
        WHEN STRPOS(st.Key, 'MSS') > 0 THEN 'MSS'
        ELSE NULL
      END
  END AS T2SolvedBy,
  
  -- T3 Solved By: Determines which T3 project resolved the ticket (if escalated to T3)
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
    ELSE NULL
  END AS T3SolvedBy,
  
  -- Tier Assist: Overall tier determination based on escalation chain
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR 
         STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'T3'
    WHEN st.Key IS NULL THEN 'T1'
    WHEN STRPOS(st.Key, 'TAC') > 0 OR 
         STRPOS(st.Key, 'CCAS') > 0 OR 
         STRPOS(st.Key, 'VOICECE') > 0 OR 
         STRPOS(st.Key, 'SMSCE') > 0 OR 
         STRPOS(st.Key, 'IOTCE') > 0 OR 
         STRPOS(st.Key, 'MSS') > 0 OR 
         STRPOS(st.Key, 'TXCE') > 0 THEN 'T2'
    ELSE NULL
  END AS TierAssist,
  
    -- T2 Escalated: Support Jira key escalated from T2 to T3 (has T3 links)
  CASE
      WHEN (
        (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
      ) THEN st.Key
    ELSE NULL
  END AS T2Escalated,
  
  -- SolvedBy: Which tier solved the ticket
  CASE
    WHEN st.Key IS NULL THEN 'T1'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN 'T3'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        st.Links_clean IS NULL OR NOT (
          STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
        )
      )
    ) THEN 'T2'
    ELSE NULL
  END AS SolvedBy,
  
  -- T2 Solved: Support Jira key solved at T2, including self-created Jira without Remedy link
  CASE
    WHEN (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        st.Links_clean IS NULL OR NOT (
          STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
        )
      )
    THEN st.Key
    ELSE NULL
  END AS T2Solved,
  
  -- T3 Solved: Support Jira key solved at T3 (has T3 links), including self-created Jira without Remedy link
  CASE
    WHEN (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    THEN st.Key
    ELSE NULL
  END AS T3Solved,
  CASE
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'SH'
  WHEN STRPOS(Key, 'CCAS') > 0 THEN 'CCAS'
  WHEN STRPOS(Key, 'TAC') > 0 THEN 'TAC'
  WHEN STRPOS(Key, 'VOICECE') > 0 THEN 'VOICECE'
  WHEN STRPOS(Key, 'IOTCE') > 0 THEN 'IOTCE'
  WHEN STRPOS(Key, 'TXCE') > 0 THEN 'TXCE'
  WHEN STRPOS(Key, 'SMSCE') > 0 THEN 'SMSCE'
  WHEN STRPOS(Key, 'MSS') > 0 THEN 'MSS'
    ELSE NULL
  END AS SolvedByProject,
  
  -- CCAS: Returns Key if it contains 'CCAS' project code
  CASE 
    WHEN STRPOS(Key, 'CCAS') > 0 THEN Key 
    ELSE NULL 
  END AS CCAS,
  
  -- MSS: Returns Key if it contains 'MSS' project code
  CASE 
    WHEN STRPOS(Key, 'MSS') > 0 THEN Key 
    ELSE NULL 
  END AS MSS,
  
  -- IOTCE: Returns Key if it contains 'IOTCE' project code
  CASE 
    WHEN STRPOS(Key, 'IOTCE') > 0 THEN Key 
    ELSE NULL 
  END AS IOTCE,
  
  -- TXCE: Returns Key if it contains 'TXCE' project code
  CASE 
    WHEN STRPOS(Key, 'TXCE') > 0 THEN Key 
    ELSE NULL 
  END AS TXCE,
  
  -- SMSCE: Returns Key if it contains 'SMSCE' project code
  CASE 
    WHEN STRPOS(Key, 'SMSCE') > 0 THEN Key 
    ELSE NULL 
  END AS SMSCE,
  
  -- VIM: Returns Key if it contains 'VIM' project code
  CASE 
    WHEN STRPOS(Key, 'VIM') > 0 THEN Key 
    ELSE NULL 
  END AS VIM,
  
  -- VME: Returns Key if it contains 'VME' project code
  CASE 
    WHEN STRPOS(Key, 'VME') > 0 THEN Key 
    ELSE NULL 
  END AS VME,
  
  -- ITHD: Returns Key if it contains 'ITHD' project code
  CASE 
    WHEN STRPOS(Key, 'ITHD') > 0 THEN Key 
    ELSE NULL 
  END AS ITHD,
  
  -- ITOPS: Returns Key if it contains 'ITOPS' project code
  CASE 
    WHEN STRPOS(Key, 'ITOPS') > 0 THEN Key 
    ELSE NULL 
  END AS ITOPS,
  
  -- GSDT: Returns Key if it contains 'GSDT' project code
  CASE 
    WHEN STRPOS(Key, 'GSDT') > 0 THEN Key 
    ELSE NULL 
  END AS GSDT,
  
  -- CCPROV: Returns Key if it contains 'CCPROV' project code
  CASE 
    WHEN STRPOS(Key, 'CCPROV') > 0 THEN Key 
    ELSE NULL 
  END AS CCPROV,
  
  -- TAC: Returns Key if it contains 'TAC' project code
  CASE 
    WHEN STRPOS(Key, 'TAC') > 0 THEN Key 
    ELSE NULL 
  END AS TAC,
  
  -- VOICECE: Returns Key if it contains 'VOICECE' project code
  CASE 
    WHEN STRPOS(Key, 'VOICECE') > 0 THEN Key 
    ELSE NULL 
  END AS VOICECE,
  
  -- Escalated by CCAS: Returns Key if CCAS AND has T3 links (AS3491, CCONB, COPS, CSCM, SH)
  CASE 
    WHEN STRPOS(Key, 'CCAS') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN Key 
    ELSE NULL 
  END AS EscalatedByCCAS,
  
  -- Escalated by T1: Returns Key if has Remedy link AND is a Jira key AND NOT Service Delivery projects
  CASE 
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL AND 
         NOT (STRPOS(st.Key, 'GSDT') > 0 OR STRPOS(st.Key, 'CCPROV') > 0)
    THEN st.Key 
    ELSE NULL 
  END AS EscalatedByT1,
  
  -- Escalated by TAC: Returns Key if TAC project AND has T3 links (AS3491, CCONB, COPS, CSCM, VIM, VME, SH)
  CASE 
    WHEN STRPOS(st.Key, 'TAC') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VIM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VME') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN st.Key
    ELSE NULL
  END AS EscalatedByTAC,
  
  -- Escalated by VOICECE: Returns Key if VOICECE project AND has T3 links (AS3491, CCONB, COPS, CSCM, VIM, VME, SH)
  CASE 
    WHEN STRPOS(st.Key, 'VOICECE') > 0 AND (
      STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VIM') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'VME') > 0 OR
      STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
    )
    THEN st.Key
    ELSE NULL
  END AS EscalatedByVOICECE,
  
  -- JiraOutstandingDuration_day: Number of days between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), DAY) AS JiraOutstandingDuration_day,
  
  -- JiraOutstandingDuration_hr: Number of hours between Jira creation and current datetime
  DATETIME_DIFF(CURRENT_DATETIME(), CAST(st.Created AS DATETIME), HOUR) AS JiraOutstandingDuration_hr,
  
  -- JiraSelfCreate: Returns Key if Jira exists but was not linked to a Remedy incident
  CASE 
    WHEN st.Key IS NOT NULL AND hd.Incident_Number IS NULL 
    THEN st.Key 
    ELSE NULL 
  END AS JiraSelfCreate,
  
  -- Lead_Time_days: Number of days between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), DAY) AS Lead_Time_days,
  
  -- Lead_Time_hr: Number of hours between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), HOUR) AS Lead_Time_hr,
  
  -- Lead_Time_mins: Number of minutes between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), MINUTE) AS Lead_Time_mins,
  
  -- Lead_Time_secs: Number of seconds between Jira creation and resolution
  DATETIME_DIFF(CAST(st.Resolved AS DATETIME), CAST(st.Created AS DATETIME), SECOND) AS Lead_Time_secs,
  
  -- MTTR_Status: Returns 'MTTRPassed' if MTTR passed condition (> 0 and <= 240 mins), otherwise 'MTTRFailed'
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240
    THEN 'MTTRPassed' 
    ELSE 'MTTRFailed' 
  END AS MTTR_Status,
  
  -- MTTR_days: MTTR converted from minutes to days
  hd.TrueMTTR_mins / 60 / 24 AS MTTR_days,
  
  -- MTTR_hr: MTTR converted from minutes to hours
  hd.TrueMTTR_mins / 60 AS MTTR_hr,
  
  -- MTTR_secs: MTTR converted from minutes to seconds
  hd.TrueMTTR_mins * 60 AS MTTR_secs,
  
  -- MTTRFailed: Returns Incident_Number if MTTR <= 0 or > 240 minutes
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRFailed,
  
  -- MTTRFailed_mins: MTTR minutes when failed
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRFailed_mins,
  
  -- MTTRFailed_hrs: MTTRFailed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins <= 0 OR hd.TrueMTTR_mins > 240 
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS MTTRFailed_hrs,
  
  -- MTTRPassed: Returns Incident_Number if MTTR > 0 and <= 240 minutes
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.Incident_Number 
    ELSE NULL 
  END AS MTTRPassed,
  
  -- MTTRPassed_mins: MTTR minutes when passed
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.TrueMTTR_mins 
    ELSE NULL 
  END AS MTTRPassed_mins,
  
  -- MTTRPassed_hrs: MTTRPassed minutes converted to hours
  CASE 
    WHEN hd.TrueMTTR_mins > 0 AND hd.TrueMTTR_mins <= 240 
    THEN hd.TrueMTTR_mins / 60 
    ELSE NULL 
  END AS MTTRPassed_hrs,
  
  -- PriorityLabel: Returns priority with numeric prefix for sorting
  CASE 
    WHEN hd.Priority = 'Critical' THEN '1 - Critical'
    WHEN hd.Priority = 'High'     THEN '2 - High'
    WHEN hd.Priority = 'Medium'   THEN '3 - Medium'
    WHEN hd.Priority = 'Low'      THEN '4 - Low'
    ELSE '5 - Null'
  END AS PriorityLabel,
  
  -- RemedyLeadTime_hrs: Number of hours between Submit_Date and Closed_Date
  DATETIME_DIFF(hd.Closed_Date, hd.Submit_Date, HOUR) AS RemedyLeadTime_hrs,
  
  -- SolvedByAS3491: Returns Key if AS3491 is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByAS3491,
  
  -- SolvedByCCONB: Returns Key if CCONB is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCCONB,
  
  -- SolvedByCOPS: Returns Key if COPS is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCOPS,
  
  -- SolvedByCSCM: Returns Key if CSCM is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedByCSCM,
  
  -- SolvedBySH: Returns Key if SH is in Links
  CASE 
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 
    THEN st.Key 
    ELSE NULL 
  END AS SolvedBySH,
  
  CASE 
    WHEN hd.ProductDescription IS NULL THEN CONCAT(shr.`Product ID`, ' ', shr.`ProductDescription`)
    ELSE hd.ProductDescription
  END AS ProductID,
  CASE 
    WHEN hd.Product_Family IS NULL THEN shr.`Product Family`
    ELSE hd.Product_Family
  END AS ProductFamily,
  shr.`SR Status`,
  st.SR_Ref AS JiraSRNo,
  st.SyncTime

FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
FULL OUTER JOIN UniqueJira AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat AND st.unique_rank = 1
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS shr
  ON CONCAT('SR', st.SR_Ref) = shr.SRNo;

-- ========================================
-- AGGREGATION METRICS (Looker Measures)
-- ========================================
-- These are calculated in Looker using COUNT_DISTINCT aggregations:
--
-- MTTRFail%: COUNT_DISTINCT(MTTRFailed) / (COUNT_DISTINCT(MTTRPassed) + COUNT_DISTINCT(MTTRFailed))
--   Percentage of Remedy tickets that failed MTTR SLA (exceeded 240 minutes or <= 0)
--
-- MTTRPass%: COUNT_DISTINCT(MTTRPassed) / (COUNT_DISTINCT(MTTRPassed) + COUNT_DISTINCT(MTTRFailed))
--   Percentage of Remedy tickets that passed MTTR SLA (within 240 minutes)
--
-- T1 LSR: COUNT_DISTINCT(T1Solved) / COUNT_DISTINCT(Incident_Number)
--   T1 Load Service Resolution rate - percentage of tickets solved entirely by T1 without escalation
--
-- T2 LSR: COUNT_DISTINCT(T2Solved) / COUNT_DISTINCT(T2 Project Keys)
--   T2 Load Service Resolution rate - percentage of T2 tickets solved without T3 escalation
--   Denominator: COUNT_DISTINCT(CASE WHEN TAC|CCAS|VOICECE|SMSCE|IOTCE|MSS|TXCE THEN Key ELSE NULL END)



