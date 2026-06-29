-- Create the Admin.DataStudioLog table for Looker Studio / Data Studio audit data.
-- This table is intended to hold report-open/activity events such as who viewed a report and when.

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.Admin.DataStudioLog` (
  event_time TIMESTAMP NOT NULL,
  actor_email STRING,
  actor_display_name STRING,
  event_name STRING,
  asset_id STRING,
  asset_name STRING,
  asset_type STRING,
  report_id STRING,
  report_name STRING,
  owner_email STRING,
  visibility STRING,
  project_id STRING,
  ip_address STRING,
  duration_seconds INT64,
  source_system STRING,
  raw_json STRING,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(event_time)
CLUSTER BY actor_email, report_id, event_name;
