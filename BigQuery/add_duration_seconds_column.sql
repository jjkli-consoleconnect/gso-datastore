-- Add DurationSeconds column to existing PipelineRuns table
-- This script adds the new DurationSeconds field for tracking pipeline execution times

-- Add the DurationSeconds column to the existing table
ALTER TABLE `pccw-internal-virt-agent-uat.GSO.PipelineRuns`
ADD COLUMN IF NOT EXISTS DurationSeconds FLOAT64;

-- Verify the column was added successfully
SELECT
  column_name,
  data_type,
  is_nullable
FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'PipelineRuns'
  AND column_name = 'DurationSeconds';
