WITH base_data AS (
  SELECT
    *,
    COALESCE(mrc_usd, 0) AS mrc_usd_nonnull
  FROM `pccw-internal-virt-agent-uat.CostItemExpiration.expired_cost_items`
),

ranked_costs AS (
  SELECT
    *,
    SUM(mrc_usd_nonnull) OVER (
      PARTITION BY snapshot_date
      ORDER BY mrc_usd_nonnull DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_total,
    SUM(mrc_usd_nonnull) OVER (PARTITION BY snapshot_date) AS total_mrc_usd,
    SUM(mrc_usd_nonnull) OVER (PARTITION BY snapshot_date) * 0.8 AS target_mrc_usd
  FROM base_data
),

flagged_rows AS (
  SELECT
    *,
    CASE
      WHEN running_total <= target_mrc_usd THEN TRUE
      WHEN running_total - mrc_usd_nonnull < target_mrc_usd THEN TRUE
      ELSE FALSE
    END AS is_top_80
  FROM ranked_costs
),

summary AS (
  SELECT
    snapshot_date,
    COUNTIF(is_top_80) AS costitemid_count_to_80pct,
    SUM(CASE WHEN is_top_80 THEN mrc_usd_nonnull ELSE 0 END) AS top_80_amount,
    MIN(CASE WHEN is_top_80 THEN mrc_usd_nonnull ELSE NULL END) AS threshold_mrc_usd_at_cutoff,
    MAX(target_mrc_usd) AS eighty_percent_of_total
  FROM flagged_rows
  GROUP BY snapshot_date
)

SELECT
  fr.snapshot_date,
  CAST(fr.costitemid AS STRING) AS costitemid,
  fr.salesrecord,
  fr.signedcompany,
  fr.vendorname,
  fr.vendorcode,
  fr.costtype,
  fr.vendortype,
  fr.reachtype,
  fr.glcode,
  fr.ccc,
  fr.potype,
  fr.ponumber,
  fr.polinenum,
  fr.lispnum,
  fr.costcategory,
  fr.costsubcategory,
  fr.nomenclature,
  fr.description,
  fr.aendaddress,
  fr.bendaddress,
  fr.billingtype,
  fr.currency,
  fr.quantity,
  fr.unitprice,
  fr.uom,
  fr.gcid,
  fr.sequence,
  fr.rateusd,
  fr.mrc,
  fr.mrc_usd,
  fr.startbillingdate,
  fr.stopbillingdate,
  fr.servicehandoverdate,
  fr.receivedqty,
  fr.reveivedamount,
  fr.receivingdate,
  fr.receivingyear,
  fr.customername,
  fr.srproductfamily,
  fr.srproducttype,
  fr.salesregion,
  fr.signedbdmname,
  fr.srstatus,
  fr.provisioningcentre,
  fr.requester,
  fr.projectnumber,
  fr.terminationnoticeday,
  fr.itemstatus,
  fr.popid,
  fr.terminationpriorsendingday,
  fr.prid,
  fr.pritemid,
  fr.wonumber,
  fr.pccwgserviceid,
  fr.vendorcircuitid,
  fr.reqdetailid,
  fr.prrequestergroup,
  fr.next_pr,
  fr.next_br,
  fr.next_ct,
  fr.cost_type_desc,
  fr.cost_category,
  fr.expire_type,
  fr.rpttype,
  fr.LISPONum,
  CASE
    WHEN fr.expire_type = 'To-be-Expired' THEN DATE_TRUNC(fr.stopbillingdate, WEEK(MONDAY))
    ELSE DATE_TRUNC(fr.snapshot_date, WEEK(MONDAY))
  END AS date_combined_week,
  DATE_TRUNC(fr.snapshot_date, WEEK(MONDAY)) AS snapshot_week,
  DATE_TRUNC(fr.stopbillingdate, WEEK(MONDAY)) AS billing_week,
  s.costitemid_count_to_80pct,
  s.eighty_percent_of_total,
  s.threshold_mrc_usd_at_cutoff,
  fr.is_top_80
FROM flagged_rows fr
JOIN summary s ON fr.snapshot_date = s.snapshot_date
WHERE NOT (fr.expire_type = 'To-be-Expired' 
  AND fr.snapshot_date < (SELECT MAX(snapshot_date) FROM flagged_rows))

