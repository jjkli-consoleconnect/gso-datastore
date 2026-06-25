# CostItemSnapSnapshot Troubleshooting Guide

## Purpose
Ensure `GSOEDPLink.CostItemSnapSnapshot` always matches the Start Gap / Stop Gap scorecards.

## Canonical Filter Logic
Base filters:
- `snapshot_date = MAX(snapshot_date)` from `GSOEDPLink.CostItem`
- `ItemCode = 'MRC'`
- `BillingType IN ('Monthly', 'Half-yearly', 'Quarterly', 'Yearly')`
- `CTStatus IS NULL OR CTStatus = '' OR CTStatus IN ('Awaiting Confirmation','Awaiting Processing','Awaiting Verification','Cancel','Denied','Saved')`
- `CostTypeCleaned = 'Direct Cost'`
- `CostType IS NULL OR CostType IN (approved list in scheduled SQL)`

Start Gap scope:
- `SRStatus IN ('Pending', 'Provisioning')`
- `ItemStatus = 'Active'`
- `StartBillingDate` within source snapshot year:
  - `StartBillingDate BETWEEN DATE_TRUNC(source_snapshot_date, YEAR) AND DATE_SUB(DATE_ADD(DATE_TRUNC(source_snapshot_date, YEAR), INTERVAL 1 YEAR), INTERVAL 1 DAY)`

Stop Gap scope:
- `SRStatus = 'Terminated'`
- `ItemStatus IN ('Active', 'Ordered')`
- `SRTerminationDate` within source snapshot year:
  - `SRTerminationDate BETWEEN DATE_TRUNC(source_snapshot_date, YEAR) AND DATE_SUB(DATE_ADD(DATE_TRUNC(source_snapshot_date, YEAR), INTERVAL 1 YEAR), INTERVAL 1 DAY)`

## Why Mismatches Happen
Most common cause is missing scorecard date-range filters:
- Start card uses `StartBillingDate` year range
- Stop card uses `SRTerminationDate` year range

If these are not applied in snapshot SQL, totals and costs will be inflated.

## Quick Parity Check (Current Snapshot Date)
```sql
WITH base AS (
  SELECT *
  FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItem`
  WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItem`)
    AND ItemCode = 'MRC'
    AND BillingType IN ('Monthly', 'Half-yearly', 'Quarterly', 'Yearly')
    AND (CTStatus IS NULL OR CTStatus = '' OR CTStatus IN ('Awaiting Confirmation','Awaiting Processing','Awaiting Verification','Cancel','Denied','Saved'))
    AND CostTypeCleaned = 'Direct Cost'
),
start_scope AS (
  SELECT *
  FROM base
  WHERE SRStatus IN ('Pending','Provisioning')
    AND ItemStatus = 'Active'
    AND StartBillingDate BETWEEN DATE '2026-01-01' AND DATE '2026-12-31'
),
stop_scope AS (
  SELECT *
  FROM base
  WHERE SRStatus = 'Terminated'
    AND ItemStatus IN ('Active','Ordered')
    AND SRTerminationDate BETWEEN DATE '2026-01-01' AND DATE '2026-12-31'
)
SELECT
  'start_gap' AS metric,
  COUNT(*) AS total,
  COUNTIF(OpenStartGapFlag = 1) AS open,
  ROUND(AVG(IF(OpenStartGapFlag = 1, CAST(StartGapDays AS FLOAT64), NULL)), 1) AS avg_days,
  ROUND(SUM(IF(OpenStartGapFlag = 1, MRC_USD, 0)), 1) AS mrc_usd,
  ROUND(SUM(IF(OpenStartGapFlag = 1, EstimatedStartGapCostUSD, 0)), 1) AS est_usd
FROM start_scope
UNION ALL
SELECT
  'stop_gap' AS metric,
  COUNT(*) AS total,
  COUNTIF(OpenStopGapFlag = 1) AS open,
  ROUND(AVG(IF(OpenStopGapFlag = 1, CAST(TerminatedNotStoppedAgingDays AS FLOAT64), NULL)), 1) AS avg_days,
  ROUND(SUM(IF(OpenStopGapFlag = 1, MRC_USD, 0)), 1) AS mrc_usd,
  ROUND(SUM(IF(OpenStopGapFlag = 1, EstimatedStopGapCostUSD, 0)), 1) AS est_usd
FROM stop_scope;
```

## Safe Recovery Procedure
1. Validate row scope for delete:
```sql
SELECT run_date, scorecard_type, COUNT(*)
FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItemSnapSnapshot`
WHERE run_date IN (CURRENT_DATE('Asia/Hong_Kong'), DATE_SUB(CURRENT_DATE('Asia/Hong_Kong'), INTERVAL 1 DAY))
GROUP BY run_date, scorecard_type;
```
2. Delete selected run dates:
```sql
DELETE FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItemSnapSnapshot`
WHERE run_date IN (CURRENT_DATE('Asia/Hong_Kong'), DATE_SUB(CURRENT_DATE('Asia/Hong_Kong'), INTERVAL 1 DAY));
```
3. Re-run scheduled SQL manually once.
4. Re-check table values and compare to scorecards.

## Current Scheduled Query
- File: `BigQuery/pccw-internal-virt-agent-uat/GSOEDPLink/scheduled_queries/CostItemSnapSnapshot.sql`
- Transfer config:
  `projects/14417857267/locations/europe-west2/transferConfigs/6a293222-0000-2a3f-b18f-94eb2c1cf75e`
- Current filter version: `v2_2026_06_12`
