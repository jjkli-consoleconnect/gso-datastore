WITH base AS (
  SELECT
    j.job_id,
    j.creation_time,
    DATE(j.creation_time) AS usage_date,
    j.user_email AS viewer_identity,
    (SELECT l.value FROM UNNEST(j.labels) AS l WHERE l.key = 'requestor' LIMIT 1) AS requestor,
    (SELECT l.value FROM UNNEST(j.labels) AS l WHERE l.key = 'looker_studio_report_id' LIMIT 1) AS looker_studio_report_id,
    (SELECT l.value FROM UNNEST(j.labels) AS l WHERE l.key = 'looker_studio_datasource_id' LIMIT 1) AS looker_studio_datasource_id,
    j.statement_type,
    j.total_bytes_processed,
    j.total_slot_ms,
    j.cache_hit,
    j.start_time,
    j.end_time,
    j.query
  FROM `region-eu`.INFORMATION_SCHEMA.JOBS_BY_PROJECT AS j
  WHERE j.job_type = 'QUERY'
    AND j.state = 'DONE'
    AND j.error_result IS NULL
    AND EXISTS (
      SELECT 1
      FROM UNNEST(j.labels) AS l
      WHERE l.key = 'requestor' AND l.value = 'looker_studio'
    )
),
daily_metrics AS (
  SELECT
    usage_date,
    looker_studio_report_id,
    looker_studio_datasource_id,
    viewer_identity,
    COUNT(*) AS query_jobs_count_day,
    COUNT(DISTINCT CONCAT(
      viewer_identity,
      '|',
      COALESCE(looker_studio_report_id, 'unknown_report_id'),
      '|',
      CAST(DIV(UNIX_SECONDS(creation_time), 600) AS STRING)
    )) AS approx_open_count_10m_day,
    MIN(creation_time) AS first_activity_at_day,
    MAX(creation_time) AS last_activity_at_day
  FROM base
  GROUP BY 1,2,3,4
)
SELECT
  b.job_id,
  b.creation_time,
  b.usage_date,
  b.viewer_identity,
  b.requestor,
  b.looker_studio_report_id,
  m.report_name AS looker_studio_report_name,
  IF(m.report_name IS NULL, FALSE, TRUE) AS report_name_mapped,
  CASE
    WHEN b.looker_studio_report_id IS NULL THEN NULL
    ELSE CONCAT('https://lookerstudio.google.com/reporting/', b.looker_studio_report_id)
  END AS looker_studio_report_url,
  b.looker_studio_datasource_id,
  d.query_jobs_count_day,
  d.approx_open_count_10m_day,
  d.first_activity_at_day,
  d.last_activity_at_day,
  b.statement_type,
  b.total_bytes_processed,
  b.total_slot_ms,
  b.cache_hit,
  b.start_time,
  b.end_time,
  b.query
FROM base b
LEFT JOIN `pccw-internal-virt-agent-uat.Admin.DataStudioReportLookup` m
  ON b.looker_studio_report_id = m.looker_studio_report_id
LEFT JOIN daily_metrics d
  ON b.usage_date = d.usage_date
 AND IFNULL(b.looker_studio_report_id, '') = IFNULL(d.looker_studio_report_id, '')
 AND IFNULL(b.looker_studio_datasource_id, '') = IFNULL(d.looker_studio_datasource_id, '')
 AND b.viewer_identity = d.viewer_identity
