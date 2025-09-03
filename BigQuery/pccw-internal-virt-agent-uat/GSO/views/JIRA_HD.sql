WITH FlattenedTierTwo AS (
  SELECT
    t.*,
    remedy_incident AS RemedyTicketNumber_flat
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
    LEFT JOIN UNNEST(t.RemedyTicketNumber) AS remedy_incident
  WHERE NOT REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAI|GTA|GDA|GKC)')
)

SELECT
  hd.Incident_Number,
  hd.Status AS hdStatus,
  hd.CaseType,
  CASE
    WHEN CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request') THEN ('Remedy' || '-' || CaseType)
    WHEN CaseType IN (
      'MCEvent-Child', 'MCEvent', 'RPO-Child', 'RPO',
      'UMW-Child', 'UMW', 'CRN-Child', 'CRN'
    ) THEN 'Remedy-Maintenance'
    WHEN st.`T` IN (
      'Incident', 'Change', 'Support Request', 'Ecosystem Health Check',
      'Proactive Alert', 'Billing Task', 'Problem', 'Sustaining Reliability Engineering',
      'Task', 'Project', 'Knowledge Management', 'Regression Testing',
      'Service Request', 'Assignment', 'Service Request with Approvals'
    ) THEN (REGEXP_EXTRACT(Key, r'^([A-Z]+)') || '-' || st.`T`)
    ELSE null
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
  st.Links,
  REGEXP_EXTRACT(Key, r'^([A-Z]+)') AS ProjectCode,
  CASE
    WHEN (
      (STRPOS(Key, 'CCAS') > 0 OR STRPOS(Key, 'TAC') > 0 OR STRPOS(Key, 'VOICECE') > 0 OR STRPOS(Key, 'IOTCE') > 0 OR STRPOS(Key, 'TXCE') > 0 OR STRPOS(Key, 'SMSCE') > 0 OR STRPOS(Key, 'MSS') > 0) AND
      (
        STRPOS(Links, 'AS3491') > 0 OR
        STRPOS(Links, 'CCONB') > 0 OR
        STRPOS(Links, 'COPS') > 0 OR
        STRPOS(Links, 'CSCM') > 0 OR
        STRPOS(Links, 'SH') > 0
      )
    ) THEN 'T3'

    WHEN (
      (STRPOS(Key, 'TAC') > 0 OR STRPOS(Key, 'CCAS') > 0 OR STRPOS(Key, 'VOICECE') > 0 OR STRPOS(Key, 'IOTCE') > 0 OR STRPOS(Key, 'TXCE') > 0 OR STRPOS(Key, 'SMSCE') > 0 OR STRPOS(Key, 'MSS') > 0) AND
      (
        Links IS NULL OR NOT (
          STRPOS(Links, 'AS3491') > 0 OR
          STRPOS(Links, 'CCONB') > 0 OR
          STRPOS(Links, 'COPS') > 0 OR
          STRPOS(Links, 'CSCM') > 0 OR
          STRPOS(Links, 'SH') > 0
        )
      )
    ) THEN 'T2'

    WHEN Key IS NULL THEN 'T1'

    ELSE NULL
  END AS SolvedBy,
  CASE
    WHEN STRPOS(Links, 'AS3491') > 0 THEN 'AS3491'
    WHEN STRPOS(Links, 'CCONB') > 0 THEN 'CCONB'
    WHEN STRPOS(Links, 'COPS') > 0 THEN 'COPS'
    WHEN STRPOS(Links, 'CSCM') > 0 THEN 'CSCM'
    WHEN STRPOS(Links, 'SH') > 0 THEN 'SH'
    WHEN STRPOS(Key, 'CCAS') > 0 THEN 'CCAS'
    WHEN STRPOS(Key, 'TAC') > 0 THEN 'TAC'
    WHEN STRPOS(Key, 'VOICECE') > 0 THEN 'VOICECE'
    WHEN STRPOS(Key, 'IOTCE') > 0 THEN 'IOTCE'
    WHEN STRPOS(Key, 'TXCE') > 0 THEN 'TXCE'
    WHEN STRPOS(Key, 'SMSCE') > 0 THEN 'SMSCE'
    WHEN STRPOS(Key, 'MSS') > 0 THEN 'MSS'
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
  st.SR_Ref AS JiraSRNo,
  st.SyncTime

FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
FULL OUTER JOIN FlattenedTierTwo AS st
  ON hd.Incident_Number = st.RemedyTicketNumber_flat
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS shr
  ON CONCAT('SR', st.SR_Ref) = shr.SRNo



