-- Snapshot query for Start Gap and Stop Gap scorecards.
-- Designed for BigQuery Scheduled Query destination table: GSOEDPLink.CostItemSnapSnapshot
-- Schedule target: daily 08:00 HKT (deploy as 00:00 UTC).

WITH meta AS (
  SELECT
    CURRENT_TIMESTAMP() AS run_ts,
    CURRENT_DATE('Asia/Hong_Kong') AS run_date_hkt,
    (
      SELECT MAX(snapshot_date)
      FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItem`
    ) AS source_snapshot_date
),
base AS (
  SELECT *
  FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItem`
  WHERE snapshot_date = (SELECT source_snapshot_date FROM meta)
    AND ItemCode = 'MRC'
    AND BillingType IN ('Monthly', 'Half-yearly', 'Quarterly', 'Yearly')
    AND (
      CTStatus IS NULL
      OR CTStatus = ''
      OR CTStatus IN (
        'Awaiting Confirmation',
        'Awaiting Processing',
        'Awaiting Verification',
        'Cancel',
        'Denied',
        'Saved'
      )
    )
    AND (
      CostType IS NULL
      OR CostType IN (
        'Network (Voice-Wholesale)',
        'Direct Cost (IPVPN/SDWAN)',
        'Direct Cost (Transmission)',
        'Direct Cost (Security)',
        'Network (Security)',
        'Direct Cost (Mobility)',
        'Direct Cost (IoD)',
        'Direct Cost (Others)',
        'Direct Cost (UCaaS)',
        'Network (ONTAPtv.com)',
        'Research and Development',
        'Network (Satellite)',
        'Network (Telex)',
        'Network (Console Partner Interconnect)',
        'Direct Cost (Media)',
        'Direct Cost (Satellite Connectivity)',
        'Direct Cost (SDI)',
        'Direct Cost (Satellite GTVN)',
        'Network (ex-MDS)',
        'Network (IoT)',
        'Network (GTVN)',
        'IT cost (Internal/Office Use)',
        'Old Direct Cost (for RFQ only)',
        'Network (Infonet)',
        'Direct Cost (Voice-Wholesale)',
        'Direct Cost (IP Transit/GIA)',
        'Network (Optify)',
        'Direct Cost (Data Center as a Product)',
        'Network (Digital Platform)',
        'SG&A',
        'Direct Cost (ex-MDS)',
        'Direct Cost (Cloud)',
        'Network (IP Transit/GIA)',
        'Network (VAS)',
        'Network (Data Center as a Product)',
        'Network (Transmission)',
        'Network (ex-MSDS)',
        'Network (IP)',
        'Network (Mobility)',
        'Direct Cost (GDS)',
        'Direct Cost (Meeting Place)',
        'Direct Cost (IoT)',
        'Direct Cost (L1)',
        'Network (Common Infrastructure)',
        'Network (Core Pop Colocation)',
        'Network (Media)'
      )
    )
    AND CostTypeCleaned = 'Direct Cost'
),
start_scope AS (
  SELECT *
  FROM base
  WHERE SRStatus IN ('Pending', 'Provisioning')
    AND ItemStatus = 'Active'
    AND StartBillingDate BETWEEN DATE_TRUNC((SELECT source_snapshot_date FROM meta), YEAR)
      AND DATE_SUB(DATE_ADD(DATE_TRUNC((SELECT source_snapshot_date FROM meta), YEAR), INTERVAL 1 YEAR), INTERVAL 1 DAY)
),
stop_scope AS (
  SELECT *
  FROM base
  WHERE SRStatus = 'Terminated'
    AND ItemStatus IN ('Active', 'Ordered')
    AND SRTerminationDate BETWEEN DATE_TRUNC((SELECT source_snapshot_date FROM meta), YEAR)
      AND DATE_SUB(DATE_ADD(DATE_TRUNC((SELECT source_snapshot_date FROM meta), YEAR), INTERVAL 1 YEAR), INTERVAL 1 DAY)
),
result_rows AS (
  SELECT
    (SELECT run_date_hkt FROM meta) AS run_date,
    (SELECT run_ts FROM meta) AS run_ts,
    (SELECT source_snapshot_date FROM meta) AS source_snapshot_date,
    DATE_TRUNC((SELECT source_snapshot_date FROM meta), MONTH) AS source_snapshot_month,
    'v2_2026_06_12' AS filter_version,
    'MRC' AS filter_itemcode,
    'Monthly|Half-yearly|Quarterly|Yearly' AS filter_billing_type,
    'NULL_OR_BLANK_OR_[Awaiting Confirmation,Awaiting Processing,Awaiting Verification,Cancel,Denied,Saved]' AS filter_ctstatus,
    'Direct Cost' AS filter_costtype_cleaned,
    'start_gap' AS scorecard_type,
    'Pending|Provisioning' AS filter_srstatus,
    'Active' AS filter_itemstatus,
    COUNT(*) AS total_cost_items,
    COUNTIF(OpenStartGapFlag = 1) AS open_gap_action_required_count,
    COUNTIF(StartGapActionRequired <> 'No Action Required') AS action_required_non_no_count,
    ROUND(AVG(IF(OpenStartGapFlag = 1, CAST(StartGapDays AS FLOAT64), NULL)), 1) AS avg_gap_duration_days,
    ROUND(SUM(IF(OpenStartGapFlag = 1, MRC_USD, 0)), 1) AS mrc_usd,
    ROUND(SUM(IF(OpenStartGapFlag = 1, EstimatedStartGapCostUSD, 0)), 1) AS estimated_gap_cost_usd
  FROM start_scope

  UNION ALL

  SELECT
    (SELECT run_date_hkt FROM meta) AS run_date,
    (SELECT run_ts FROM meta) AS run_ts,
    (SELECT source_snapshot_date FROM meta) AS source_snapshot_date,
    DATE_TRUNC((SELECT source_snapshot_date FROM meta), MONTH) AS source_snapshot_month,
    'v2_2026_06_12' AS filter_version,
    'MRC' AS filter_itemcode,
    'Monthly|Half-yearly|Quarterly|Yearly' AS filter_billing_type,
    'NULL_OR_BLANK_OR_[Awaiting Confirmation,Awaiting Processing,Awaiting Verification,Cancel,Denied,Saved]' AS filter_ctstatus,
    'Direct Cost' AS filter_costtype_cleaned,
    'stop_gap' AS scorecard_type,
    'Terminated' AS filter_srstatus,
    'Active|Ordered' AS filter_itemstatus,
    COUNT(*) AS total_cost_items,
    COUNTIF(OpenStopGapFlag = 1) AS open_gap_action_required_count,
    COUNTIF(StopGapActionRequired <> 'No Action Required') AS action_required_non_no_count,
    ROUND(AVG(IF(OpenStopGapFlag = 1, CAST(TerminatedNotStoppedAgingDays AS FLOAT64), NULL)), 1) AS avg_gap_duration_days,
    ROUND(SUM(IF(OpenStopGapFlag = 1, MRC_USD, 0)), 1) AS mrc_usd,
    ROUND(SUM(IF(OpenStopGapFlag = 1, EstimatedStopGapCostUSD, 0)), 1) AS estimated_gap_cost_usd
  FROM stop_scope
)
SELECT
  r.*
FROM result_rows r
WHERE NOT EXISTS (
  SELECT 1
  FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItemSnapSnapshot` t
  WHERE t.run_date = r.run_date
    AND t.scorecard_type = r.scorecard_type
);
