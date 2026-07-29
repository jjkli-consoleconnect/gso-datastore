-- Cleanup script for SHRPeople RSM Name column duplication
-- This script:
--   1. Backfills RSMName from the legacy "RSM Name" and "RSM_Name" columns (if any data exists there)
--   2. Drops both legacy columns, keeping only RSMName (matching the source CSV header)
--
-- Run this ONCE after deploying the updated Cloud Function.
-- The updated Cloud Function now writes to RSMName (no space, no underscore).

-- Step 1: Backfill RSMName from legacy "RSM Name" column where RSMName is empty
UPDATE `pccw-internal-virt-agent-uat.GSO.SHRPeople`
SET `RSMName` = `RSM Name`
WHERE (`RSMName` IS NULL OR TRIM(`RSMName`) = '')
  AND `RSM Name` IS NOT NULL
  AND TRIM(`RSM Name`) != '';

-- Step 2: Backfill RSMName from legacy "RSM_Name" column where RSMName is still empty
UPDATE `pccw-internal-virt-agent-uat.GSO.SHRPeople`
SET `RSMName` = `RSM_Name`
WHERE (`RSMName` IS NULL OR TRIM(`RSMName`) = '')
  AND `RSM_Name` IS NOT NULL
  AND TRIM(`RSM_Name`) != '';

-- Step 3: Drop both legacy columns, keep only RSMName
-- BigQuery does not support DROP COLUMN via ALTER TABLE in standard SQL.
-- Use CREATE OR REPLACE TABLE to drop both columns at once:
CREATE OR REPLACE TABLE `pccw-internal-virt-agent-uat.GSO.SHRPeople` AS
SELECT * EXCEPT(`RSM Name`, `RSM_Name`)
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`;

-- Step 4: Verify the cleanup
-- Check that only RSMName remains and is populated
SELECT
  COUNTIF(`RSMName` IS NOT NULL AND TRIM(`RSMName`) != '') AS rsmname_populated,
  COUNT(*) AS total_rows
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`;