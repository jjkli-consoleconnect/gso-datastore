-- SRInventory LEFT JOIN HelpDeskAllNOC
--
-- Join logic:
--   SRInventory.SR        = plain numeric string, e.g. "232834"
--   HelpDeskAllNOC.SRno   = stored with literal surrounding quotes + SR prefix, e.g. `"SR232834"`
--   Normalisation strips the outer quotes and the SR prefix, then compares as INT64
--   to handle any leading-zero differences between the two sides.
--
-- All 114 445 SRInventory rows are preserved (LEFT JOIN).
-- ~18 633 distinct SRs have at least one matching HelpDesk incident.
-- Assigned_Group is aliased as NOC.

SELECT
  -- ── SRInventory columns ────────────────────────────────────────────────────
  sri.SR,
  sri.Cusid,
  sri.CusGrpID,
  sri.GCSCRegion,
  sri.Circuit_ID,
  sri.SaleStatusID,
  sri.Signed_BDM,
  sri.Segment,
  sri.VIP,
  sri.Customer_Name,
  sri.Product_ID,
  sri.Product_Family,
  sri.Sales_Region,
  sri.Circuit_Owner,
  sri.RSM_name_primary,
  sri.RSM_name_alternative,
  sri.DateInserted,

  -- ── HelpDeskAllNOC columns ─────────────────────────────────────────────────
  hd.SRno,
  hd.Incident_Number,
  hd.Status,
  hd.CaseType,
  hd.Assigned_Group                AS NOC,
  hd.Categorization_Tier_1,
  hd.Categorization_Tier_2,
  hd.Categorization_Tier_3,
  hd.GCSC_1st_Customer_Update,
  hd.GCSC_2nd_Customer_Update,
  hd.GCSC_3rd_Customer_Update,
  hd.Initial_Response_Time,
  hd.Second_Response_Time,
  hd.Third_Response_Time,
  hd.Prod_ID,
  hd.Fault_Cause,
  hd.FaultCauseDetail,
  hd.Closed_Date,
  hd.Submit_Date,
  hd.Assignee,
  hd.Closed_By,
  hd.Submitter,
  hd.TrueMTTR_mins,
  hd.Cust_ID,
  hd.Carrier,
  hd.Customer_Name                 AS HD_Customer_Name,
  hd.LastResolvedDate,
  hd.ReportedDate,
  hd.RespondedDate,
  hd.LastModifiedDate,
  hd.ReportedBy,
  hd.Product_Family                AS HD_Product_Family,
  hd.ProductDescription,
  hd.GSMP_Circuit_ID,
  hd.inserted_at,
  hd.Urgency,
  hd.Priority

FROM `pccw-internal-virt-agent-uat.GSO.SRInventory` AS sri
LEFT JOIN `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS hd
  ON SAFE_CAST(sri.SR AS INT64)
   = SAFE_CAST(
       REGEXP_REPLACE(TRIM(hd.SRno, chr(34)), r'^SR0*', '')
     AS INT64)

ORDER BY
  sri.SR,
  hd.Submit_Date DESC
;
