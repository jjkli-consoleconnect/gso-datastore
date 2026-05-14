-- GSO_CenterOps_CircuitMetrics
-- One row per ticket, enriched with SHRPeople circuit owner & product context
-- Used for Center Operations dashboard: monthly circuit availability & fault rate

CREATE OR REPLACE TABLE `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics` AS

SELECT DISTINCT
  -- Ticket identifiers
  hdwl.Incident_Number,
  hdwl.Status,
  hdwl.CaseType,
  
  -- Dates
  hdwl.Reported_Date,
  hdwl.Responded_Date,
  hdwl.Closed_Date,
  hdwl.LastResolvedDate,
  EXTRACT(YEAR FROM hdwl.Reported_Date) AS Report_Year,
  EXTRACT(MONTH FROM hdwl.Reported_Date) AS Report_Month,
  
  -- Circuit & Assignment
  hdwl.GSMP_Circuit_ID,
  hdwl.Assigned_Group,
  
  -- SHRPeople enrichment
  shr.Circuit_Owner,
  shr.Product_Family,
  shr.Product_ID,
  shr.CustName,
  shr.SR_Status AS Circuit_Status,
  
  -- MTTR and performance
  hdwl.TrueMTTR_mins,
  CAST(hdwl.`1st_Response_Minutes` AS INT64) AS First_Response_Minutes,
  
  -- Fault analysis (AI-enriched)
  hdwl.Fault_Cause,
  hdwl.Fault_Cause_Detail,
  hdwl.AIAtFault,
  hdwl.AIAtFault_Audit,
  hdwl.AI_FaultDomain,
  hdwl.AI_CarrierVendor,
  hdwl.AI_PrimarySymptom,
  hdwl.AI_LikelyRootCause,
  hdwl.AI_ConfidenceScore,
  
  -- Metadata
  hdwl.Priority,
  hdwl.Urgency,
  hdwl.Categorization_Tier_1,
  hdwl.Categorization_Tier_2,
  hdwl.Categorization_Tier_3,
  hdwl.Cust_ID,
  hdwl.SRno,
  hdwl.ProductDescription
  
FROM `pccw-internal-virt-agent-uat.GSO.HDWL` hdwl
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.SHRPeople` shr
  ON hdwl.GSMP_Circuit_ID = shr.Insight_Circuit_ID
  AND shr.SR_Status IN ('Upgraded', 'Available')  -- Active circuits only
  
WHERE hdwl.Incident_Number IS NOT NULL
  AND hdwl.Reported_Date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)  -- Last ~2 years
;
