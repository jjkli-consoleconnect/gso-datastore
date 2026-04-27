SELECT
  -- HelpDeskAllNOC fields (Ticket Table)
  h.Incident_Number,
  h.Status,
  h.CaseType,
  h.ReportedDate as Reported_Date,
  h.RespondedDate as Responded_Date,
  h.LastResolvedDate,
  h.Submit_Date,
  h.Closed_Date,
  h.Assigned_Group,
  h.Assignee,
  h.Submitter,
  h.ReportedBy,
  h.Closed_By,
  h.Categorization_Tier_1,
  h.Categorization_Tier_2,
  h.Categorization_Tier_3,
  h.Prod_ID,
  h.Product_Family,
  h.ProductDescription,
  h.Fault_Cause,
  h.FaultCauseDetail as Fault_Cause_Detail,
  h.Priority,
  h.Urgency,
  h.SRno,
  h.Cust_ID,
  h.Carrier,
  h.Customer_Name,
  h.GSMP_Circuit_ID,
  h.TrueMTTR_mins,
  h.GCSC_1st_Customer_Update,
  h.GCSC_2nd_Customer_Update,
  CASE WHEN h.Status = 'Assigned' THEN "1-Assigned"
        WHEN h.Status = 'In Progress' THEN "2-In Progress"
        WHEN h.Status = 'Pending' THEN "3-Pending"
        WHEN h.Status = 'Resolved' THEN "4-Resolved"
        WHEN h.Status = 'Closed' THEN "5-Closed"
        WHEN h.Status = 'Cancelled' THEN "6-Cancelled"
    ELSE NULL 
  END AS TicketProcess,
  -- KPI Calculations (Custom)
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.ReportedDate IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.ReportedDate, MINUTE)
    ELSE NULL
  END AS `1st_Response_Minutes`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.ReportedDate IS NOT NULL
    THEN CASE 
      WHEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.ReportedDate, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS `1st_Response_PassFail`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.GCSC_2nd_Customer_Update IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_2nd_Customer_Update, h.GCSC_1st_Customer_Update, MINUTE)
    ELSE NULL
  END AS `2nd_Response_Minutes`,
  CASE
    WHEN h.GCSC_1st_Customer_Update IS NOT NULL AND h.GCSC_2nd_Customer_Update IS NOT NULL
    THEN CASE 
      WHEN TIMESTAMP_DIFF(h.GCSC_2nd_Customer_Update, h.GCSC_1st_Customer_Update, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS `2nd_Response_PassFail`,
  h.LastModifiedDate as LastModifiedDateHD,
  
  -- WorkLogAllNOC fields
  w.WorkLog_ID,
  w.WorkLog_Type,
  w.WorkLog_Submit_Date,
  w.WorkLog_Submitter,
  w.Last_Modified_Date as LastModifiedDateWL,
  w.Last_Modified_By,
  w.ExtractedDescription,
  
  -- Analytics
  COUNT(w.WorkLog_ID) OVER (PARTITION BY h.Incident_Number) as WorkLog_Count,
  ROW_NUMBER() OVER (PARTITION BY h.Incident_Number ORDER BY w.WorkLog_Submit_Date) as WorkLog_Sequence,

  -- AI Infused Fields
  ai.AIFirstResponse,
  ai.AIFirstResponseTimestamp,
  ai.AIFirstResponse_Audit
  
FROM
  `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
  
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
  ON h.Incident_Number = w.Incident_Number

LEFT JOIN (
  SELECT
    Incident_Number,
    AIFirstResponse,
    AIFirstResponseTimestamp,
    AIFirstResponse_Audit,
    ROW_NUMBER() OVER (
      PARTITION BY Incident_Number
      ORDER BY ClassifiedAt DESC
    ) AS rn
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
) ai
  ON ai.Incident_Number = h.Incident_Number
  AND ai.rn = 1
  
ORDER BY
  h.Incident_Number,
  w.WorkLog_Submit_Date

