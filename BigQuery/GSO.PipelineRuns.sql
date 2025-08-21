-- Dataset: GSO
-- Table:   PipelineRuns
-- Notes:
--  - Partitioned by DATE(RunTime)
--  - Clustered by PipelineName, RunID
--  - RunTime is required and should be set in DML as CURRENT_TIMESTAMP()

-- Create dataset if not exists in the target project
CREATE SCHEMA IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO`;

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.PipelineRuns` (
  RunTime      TIMESTAMP NOT NULL,          -- Set with CURRENT_TIMESTAMP() at insert/merge time
  PipelineName STRING   NOT NULL,
  WindowStart  TIMESTAMP,
  WindowEnd    TIMESTAMP,
  RowsMerged   INT64,
  LogLevel     STRING,
  Message      STRING,
  RunID        STRING,                      -- Correlates a run across steps/scripts
  Status       STRING,                      -- e.g., SUCCESS / ERROR
  ErrorCode    STRING,
  Context      JSON                         -- Optional structured metadata (or switch to STRING if preferred)
)
PARTITION BY DATE(RunTime)
CLUSTER BY PipelineName, RunID;
