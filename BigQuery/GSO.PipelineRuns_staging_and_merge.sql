-- Replace {uuid} with a unique suffix per run (e.g., a UUIDv4 without dashes)

-- 1) Create staging table (no RunTime column)
CREATE TABLE `pccw-internal-virt-agent-uat.GSO.PipelineRuns_stage_{uuid}` (
  PipelineName STRING NOT NULL,
  WindowStart  TIMESTAMP,
  WindowEnd    TIMESTAMP,
  RowsMerged   INT64,
  LogLevel     STRING,
  Message      STRING,
  RunID        STRING,
  Status       STRING,
  ErrorCode    STRING,
  Context      JSON
);

-- INSERT INTO `pccw-internal-virt-agent-uat.GSO.PipelineRuns_stage_{uuid}`
-- (PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, Context)
-- VALUES (@pipeline, @ws, @we, @rows, @level, @msg, @runid, @status, @err, CAST(@ctx AS JSON));

-- 3) Merge into target, setting RunTime in BigQuery
MERGE `pccw-internal-virt-agent-uat.GSO.PipelineRuns` T
USING `pccw-internal-virt-agent-uat.GSO.PipelineRuns_stage_{uuid}` S
ON T.PipelineName = S.PipelineName AND T.RunID = S.RunID
WHEN NOT MATCHED THEN
  INSERT (RunTime, PipelineName, WindowStart, WindowEnd, RowsMerged, LogLevel, Message, RunID, Status, ErrorCode, Context)
  VALUES (CURRENT_TIMESTAMP(), S.PipelineName, S.WindowStart, S.WindowEnd, S.RowsMerged, S.LogLevel, S.Message, S.RunID, S.Status, S.ErrorCode, S.Context);

-- 4) Clean up staging
DROP TABLE `pccw-internal-virt-agent-uat.GSO.PipelineRuns_stage_{uuid}`;
