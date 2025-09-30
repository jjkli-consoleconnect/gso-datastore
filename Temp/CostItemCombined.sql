SELECT
  snapshot_date,
  CAST(base.costitemid AS STRING) AS costitemid,
  salesrecord,
  signedcompany,
  vendorname,
  vendorcode,
  costtype,
  vendortype,
  reachtype,
  glcode,
  ccc,
  potype,
  ponumber,
  polinenum,
  lispnum,
  costcategory,
  costsubcategory,
  nomenclature,
  description,
  aendaddress,
  bendaddress,
  billingtype,
  currency,
  quantity,
  unitprice,
  uom,
  gcid,
  sequence,
  rateusd,
  mrc,
  mrc_usd,
  startbillingdate,
  stopbillingdate,
  servicehandoverdate,
  receivedqty,
  reveivedamount,
  receivingdate,
  receivingyear,
  customername,
  srproductfamily,
  srproducttype,
  salesregion,
  signedbdmname,
  srstatus,
  provisioningcentre,
  requester,
  projectnumber,
  terminationnoticeday,
  itemstatus,
  popid,
  terminationpriorsendingday,
  prid,
  pritemid,
  wonumber,
  pccwgserviceid,
  vendorcircuitid,
  reqdetailid,
  prrequestergroup,
  next_pr,
  next_br,
  next_ct,
  cost_type_desc,
  cost_category,
  expire_type,
  rpttype,
  LISPONum,

  -- New column based on your logic
  CASE
    WHEN expire_type = 'To-be-Expired' THEN DATE_TRUNC(stopbillingdate, WEEK(MONDAY))
    ELSE DATE_TRUNC(snapshot_date, WEEK(MONDAY))
  END AS DateCombined,

  -- Fields for top 80% analysis (these will be filled from the ranked CTE)
  IFNULL(top80.top_80_count, 0) AS top_80_count,
  IFNULL(top80.top_80_amount, 0.0) AS top_80_amount,
  IFNULL(rk.is_top_80, FALSE) AS is_top_80

FROM
  -- base data
  `pccw-internal-virt-agent-uat.CostItemExpiration.expired_cost_items` base

-- CTE to compute running sum and top 80% aggregates (single row)
CROSS JOIN (
  WITH base_cte AS (
    SELECT *, COALESCE(mrc_usd, 0) AS mrc_usd_nonnull FROM `pccw-internal-virt-agent-uat.CostItemExpiration.expired_cost_items`
    WHERE DATE(snapshot_date) >= '2025-09-15'
  ),
  total AS (
    SELECT SUM(mrc_usd_nonnull) AS total_mrc FROM base_cte
  ),
  ranked AS (
    SELECT
      costitemid,
      mrc_usd_nonnull,
      ROW_NUMBER() OVER (ORDER BY mrc_usd_nonnull DESC) AS rn,
      SUM(mrc_usd_nonnull) OVER (ORDER BY mrc_usd_nonnull DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_sum
    FROM base_cte
  ),
  threshold AS (
    SELECT total_mrc * 0.8 AS thresh FROM total
  ),
  flagged AS (
    SELECT
      r.costitemid,
      r.mrc_usd_nonnull,
      r.rn,
      r.running_sum,
      t.thresh,
      -- mark rows that are part of the top 80% (include the row that crosses the threshold)
      CASE WHEN r.running_sum <= t.thresh THEN TRUE
           WHEN r.running_sum - r.mrc_usd_nonnull < t.thresh THEN TRUE
           ELSE FALSE END AS is_top_80
    FROM ranked r CROSS JOIN threshold t
  )
  SELECT
    COUNTIF(is_top_80) AS top_80_count,
    SUM(CASE WHEN is_top_80 THEN mrc_usd_nonnull ELSE 0 END) AS top_80_amount
  FROM flagged
) top80

-- per-row flag join (to get is_top_80 for each costitem)
LEFT JOIN (
  WITH base_cte AS (
    SELECT *, COALESCE(mrc_usd, 0) AS mrc_usd_nonnull FROM `pccw-internal-virt-agent-uat.CostItemExpiration.expired_cost_items`
    WHERE DATE(snapshot_date) >= '2025-09-15'
  ),
  total AS (
    SELECT SUM(mrc_usd_nonnull) AS total_mrc FROM base_cte
  ),
  ranked AS (
    SELECT
      costitemid,
      mrc_usd_nonnull,
      ROW_NUMBER() OVER (ORDER BY mrc_usd_nonnull DESC) AS rn,
      SUM(mrc_usd_nonnull) OVER (ORDER BY mrc_usd_nonnull DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_sum
    FROM base_cte
  ),
  threshold AS (
    SELECT total_mrc * 0.8 AS thresh FROM total
  )
  SELECT costitemid, 
    CASE WHEN running_sum <= thresh THEN TRUE
         WHEN running_sum - mrc_usd_nonnull < thresh THEN TRUE
         ELSE FALSE END AS is_top_80
  FROM ranked r CROSS JOIN threshold t
) rk
ON CAST(base.costitemid AS STRING) = CAST(rk.costitemid AS STRING)

WHERE DATE(base.snapshot_date) >= '2025-09-15'
