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
  WHERE NOT REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAI|GTA|GDA|GKC|OCR|QMS|CSM|GSOSI)')
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
    WHEN STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0 THEN 'T3'

    WHEN (
      (STRPOS(Key, 'CCAS') > 0 OR STRPOS(Key, 'TAC') > 0 OR STRPOS(Key, 'VOICECE') > 0 OR STRPOS(Key, 'IOTCE') > 0 OR STRPOS(Key, 'TXCE') > 0 OR STRPOS(Key, 'SMSCE') > 0 OR STRPOS(Key, 'MSS') > 0 OR STRPOS(Key, 'VIM') > 0 OR STRPOS(Key, 'VME') > 0) AND
      (
        STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
        STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0
      )
    ) THEN 'T3'

    WHEN (
      (STRPOS(Key, 'TAC') > 0 OR STRPOS(Key, 'CCAS') > 0 OR STRPOS(Key, 'VOICECE') > 0 OR STRPOS(Key, 'IOTCE') > 0 OR STRPOS(Key, 'TXCE') > 0 OR STRPOS(Key, 'SMSCE') > 0 OR STRPOS(Key, 'MSS') > 0 OR STRPOS(Key, 'VIM') > 0 OR STRPOS(Key, 'VME') > 0) AND
      (
        st.Links_clean IS NULL OR NOT (
          STRPOS(COALESCE(st.Links_clean, ''), 'AS3491') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CCONB') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'COPS') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'CSCM') > 0 OR
          STRPOS(COALESCE(st.Links_clean, ''), 'SH') > 0
        )
      )
    ) THEN 'T2'

    WHEN Key IS NULL THEN 'T1'

    ELSE NULL
  END AS SolvedBy,
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
FULL OUTER JOIN FlattenedTierTwo AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS shr
  ON CONCAT('SR', st.SR_Ref) = shr.SRNo


