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
  WHERE NOT REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAI|GTA|GDA|GKC|OCR|QMS|CSM|GSOSI|SH)')
),
RankedJira AS (
  -- Deduplicate: per Remedy incident, pick the primary Jira (prioritize T2 projects)
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY RemedyTicketNumber_flat ORDER BY 
      CASE 
        WHEN STRPOS(Key, 'TAC') > 0 OR STRPOS(Key, 'CCAS') > 0 OR STRPOS(Key, 'VOICECE') > 0 OR 
             STRPOS(Key, 'IOTCE') > 0 OR STRPOS(Key, 'TXCE') > 0 OR STRPOS(Key, 'SMSCE') > 0 THEN 1
        ELSE 2
      END,
      Key DESC
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
  )
  WHERE unique_rank = 1
)
SELECT
  hd.Incident_Number,
  hd.Status AS hdStatus,
  hd.CaseType,
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
  -- T1 Escalated: Remedy ticket escalated by T1 (has any Jira key)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NOT NULL THEN hd.Incident_Number
    ELSE NULL
  END AS T1Escalated,
  
  -- T1 Solved: Remedy ticket solved by T1 (no Jira key, no escalation)
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND st.Key IS NULL THEN hd.Incident_Number
    ELSE NULL
  END AS T1Solved,
  
  -- T2 Escalated: T2 project escalated to T3 (has T3 links) - sequential escalation
  CASE
    WHEN hd.Incident_Number IS NOT NULL AND (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0 OR STRPOS(st.Key, 'VIM') > 0 OR STRPOS(st.Key, 'VME') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN hd.Incident_Number
    ELSE NULL
  END AS T2Escalated,
  
  -- SolvedBy: Which tier solved the ticket
  CASE
    WHEN st.Key IS NULL THEN 'T1'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0 OR STRPOS(st.Key, 'VIM') > 0 OR STRPOS(st.Key, 'VME') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN 'T3'
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0 OR STRPOS(st.Key, 'VIM') > 0 OR STRPOS(st.Key, 'VME') > 0) AND
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
  
  -- T3 Solved: T2 project escalated to T3 (SH in Links or T3 links present)
  CASE
    WHEN (
      (STRPOS(st.Key, 'TAC') > 0 OR STRPOS(st.Key, 'CCAS') > 0 OR STRPOS(st.Key, 'VOICECE') > 0 OR STRPOS(st.Key, 'IOTCE') > 0 OR STRPOS(st.Key, 'TXCE') > 0 OR STRPOS(st.Key, 'SMSCE') > 0 OR STRPOS(st.Key, 'MSS') > 0 OR STRPOS(st.Key, 'VIM') > 0 OR STRPOS(st.Key, 'VME') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN st.Key
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
  WHEN STRPOS(Key, 'VIM') > 0 THEN 'VIM'
  WHEN STRPOS(Key, 'VME') > 0 THEN 'VME'
    ELSE NULL
  END AS SolvedByProject,
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
  ON CONCAT('SR', st.SR_Ref) = shr.SRNo


