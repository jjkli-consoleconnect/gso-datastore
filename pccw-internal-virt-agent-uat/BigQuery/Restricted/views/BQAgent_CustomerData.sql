-- Restricted.TicketMRC view: ticket + MRC enrichment.
-- SR product enrichment joined from Mirror.EDP-SR ù the EU cross-region copy of
-- GSOEDPLink.EDP-SR (daily mirror of edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr).
-- Previously joined GSO.SHRPeople.
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
  COALESCE(NULLIF(h.Prod_ID, ''), shr.Product_ID) AS Prod_ID,
  COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) AS Product_Family,
  COALESCE(NULLIF(h.ProductDescription, ''), shr.ProductDescription) AS ProductDescription,
  h.Fault_Cause,
  h.FaultCauseDetail as Fault_Cause_Detail,
  h.inserted_at,
  h.Summary,
  h.Fault_Location,
  h.Service_Type,
  ai.AI_FaultCause AS AIFaultCause,
  h.Priority,
  h.Urgency,
  h.SRno,
  h.Cust_ID,
  h.Carrier,
  h.Customer_Name,
  h.GSMP_Circuit_ID,
  NULLIF(ARRAY_TO_STRING(h.RelatedItemRequestID, ' | '), '') AS Related_Item_Request_ID,
  NULLIF(ARRAY_TO_STRING(h.RelatedItemDescription, ' | '), '') AS Related_Item_Description,
  NULLIF(ARRAY_TO_STRING(h.RelatedItemRelatedTicketID, ' | '), '') AS Related_Item_Ticket_ID,
  NULLIF(ARRAY_TO_STRING(h.RelatedItemAssociationType, ' | '), '') AS Related_Item_Association_Type,
  ci.MRC_USD,
  shr.Monthly_Revenue,
  h.TrueMTTR_mins,
  h.GCSC_1st_Customer_Update,
  h.GCSC_2nd_Customer_Update,
  h.GCSC_3rd_Customer_Update,
  -- MTTR Status (Custom): pass if > 0 and <= 240 mins; 7 days (10080 mins) for Mobility & IoT
  CASE
    WHEN h.TrueMTTR_mins > 0 AND h.TrueMTTR_mins <= (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN 'MTTRPassed'
    ELSE 'MTTRFailed'
  END AS MTTR_Status,
  CASE
    WHEN h.TrueMTTR_mins <= 0 OR h.TrueMTTR_mins > (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.Incident_Number
    ELSE NULL
  END AS MTTRFailed,
  CASE
    WHEN h.TrueMTTR_mins <= 0 OR h.TrueMTTR_mins > (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.TrueMTTR_mins
    ELSE NULL
  END AS MTTRFailed_mins,
  CASE
    WHEN h.TrueMTTR_mins <= 0 OR h.TrueMTTR_mins > (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.TrueMTTR_mins / 60
    ELSE NULL
  END AS MTTRFailed_hrs,
  CASE
    WHEN h.TrueMTTR_mins > 0 AND h.TrueMTTR_mins <= (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.Incident_Number
    ELSE NULL
  END AS MTTRPassed,
  CASE
    WHEN h.TrueMTTR_mins > 0 AND h.TrueMTTR_mins <= (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.TrueMTTR_mins
    ELSE NULL
  END AS MTTRPassed_mins,
  CASE
    WHEN h.TrueMTTR_mins > 0 AND h.TrueMTTR_mins <= (CASE WHEN COALESCE(NULLIF(h.Product_Family, ''), shr.Product_Family) = 'Mobility & IoT' THEN 10080 ELSE 240 END)
    THEN h.TrueMTTR_mins / 60
    ELSE NULL
  END AS MTTRPassed_hrs,
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
  CASE
    WHEN h.GCSC_2nd_Customer_Update IS NOT NULL AND h.GCSC_3rd_Customer_Update IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_3rd_Customer_Update, h.GCSC_2nd_Customer_Update, MINUTE)
    ELSE NULL
  END AS `3rd_Response_Minutes`,
  CASE
    WHEN h.GCSC_2nd_Customer_Update IS NOT NULL AND h.GCSC_3rd_Customer_Update IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(h.GCSC_3rd_Customer_Update, h.GCSC_2nd_Customer_Update, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE 'No Response'
  END AS `3rd_Response_PassFail`,
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
  ai.AIFirstResponse_Audit,
  ai.AIAtFault,
  ai.AIAtFault_Audit,
  ai.AI_FaultDomain,
  ai.AI_FaultCause,
  ai.AI_FaultCause_Audit,
  ai.AI_CarrierVendor,
  ai.AI_PrimarySymptom,
  ai.AI_LikelyRootCause,
  ai.AI_ConfidenceScore,
  ai.AI_EvidenceSummary,
  ai.AI_DeviceName,
  ai.AI_CircuitReference,

  -- PagerDuty escalation fields
  pd.pagerduty_escalation_count,
  pd.pagerduty_escalation_policies_used

FROM
  `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
  
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
  ON h.Incident_Number = w.Incident_Number

LEFT JOIN (
  -- SR product enrichment now sourced from the daily EDP mirror (GSOEDPLink.EDP-SR)
  SELECT
    CONCAT('SR', CAST(sr_id AS STRING)) AS SRNo,
    product_id AS Product_ID,
    product_family AS Product_Family,
    product_description AS ProductDescription,
    monthly_revenue AS Monthly_Revenue
  FROM `pccw-internal-virt-agent-uat.Mirror.EDP-SR`
) shr
  ON CASE
    WHEN REGEXP_REPLACE(h.SRno, r'"', '') LIKE 'SR%'
      THEN REGEXP_REPLACE(h.SRno, r'"', '')
    ELSE CONCAT('SR', REGEXP_REPLACE(h.SRno, r'"', ''))
  END = shr.SRNo

LEFT JOIN (
  SELECT
    CONCAT('SR', CAST(SalesRecord AS STRING)) AS SalesRecordKey,
    SUM(MRC_USD) AS MRC_USD
  FROM `pccw-internal-virt-agent-uat.Mirror.all_cost_items_report`
  GROUP BY SalesRecordKey
) ci
  ON CASE
    WHEN REGEXP_REPLACE(h.SRno, r'"', '') LIKE 'SR%'
      THEN REGEXP_REPLACE(h.SRno, r'"', '')
    ELSE CONCAT('SR', REGEXP_REPLACE(h.SRno, r'"', ''))
  END = ci.SalesRecordKey

LEFT JOIN (
  SELECT
    Incident_Number,
    AIFirstResponse,
    AIFirstResponseTimestamp,
    AIFirstResponse_Audit,
    AIAtFault,
    AIAtFault_Audit,
    AI_FaultDomain,
    AI_FaultCause,
    AI_FaultCause_Audit,
    AI_CarrierVendor,
    AI_PrimarySymptom,
    AI_LikelyRootCause,
    AI_ConfidenceScore,
    AI_EvidenceSummary,
    AI_DeviceName,
    AI_CircuitReference,
    ROW_NUMBER() OVER (
      PARTITION BY Incident_Number
      ORDER BY ClassifiedAt DESC
    ) AS rn
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL_AIInfused`
) ai
  ON ai.Incident_Number = h.Incident_Number
  AND ai.rn = 1

LEFT JOIN (
  SELECT
    RemedyIncidentNumber,
    COUNT(*) AS pagerduty_escalation_count,
    STRING_AGG(escalation_policy_label, ', ' ORDER BY sort_key) AS pagerduty_escalation_policies_used
  FROM (
    SELECT DISTINCT
      RemedyIncidentNumber,
      escalation_policy_label,
      CASE
        WHEN REGEXP_CONTAINS(escalation_policy_label, r'T[0-9]+') THEN CAST(REGEXP_EXTRACT(escalation_policy_label, r'T([0-9]+)') AS INT64)
        ELSE 999
      END AS sort_key
    FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentCleansed`
    WHERE RemedyIncidentNumber IS NOT NULL
      AND escalation_policy_label IS NOT NULL
  )
  GROUP BY RemedyIncidentNumber
) pd
  ON h.Incident_Number = pd.RemedyIncidentNumber

ORDER BY
  h.Incident_Number,
  w.WorkLog_Submit_Date

