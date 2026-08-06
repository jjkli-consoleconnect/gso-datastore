WITH base AS (
  SELECT
    conversation_id,
    requisitionStartTime,
    requisitionDuration_sec AS dur_hardcoded,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    TIMESTAMP_DIFF(action_2_complete_timestamp, action_2_start_timestamp, MICROSECOND)/1e6 AS action2_span_sec,
    action_2_complete_timestamp IS NULL AS robust_null,
    requisitionDuration_sec IS NULL AS hardcoded_null,
    action_2_start_timestamp IS NULL AS start_null
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  COUNT(*) AS rows_30d,
  COUNTIF(hardcoded_null) AS hardcoded_null_rows,
  COUNTIF(robust_null) AS robust_null_rows,
  COUNTIF(start_null) AS start_null_rows,
  ROUND(AVG(dur_hardcoded),3) AS avg_hardcoded,
  ROUND(AVG(dur_robust),3) AS avg_robust,
  ROUND(AVG(IF(robust_null, NULL, dur_robust)),3) AS avg_robust_ignore_null,
  ROUND(AVG(IF(hardcoded_null, NULL, dur_hardcoded)),3) AS avg_hardcoded_ignore_null,
  ROUND(APPROX_QUANTILES(dur_robust,100)[OFFSET(50)],3) AS p50_robust,
  ROUND(APPROX_QUANTILES(dur_robust,100)[OFFSET(90)],3) AS p90_robust,
  ROUND(APPROX_QUANTILES(dur_robust,100)[OFFSET(95)],3) AS p95_robust,
  ROUND(APPROX_QUANTILES(dur_robust,100)[OFFSET(99)],3) AS p99_robust,
  ROUND(MAX(dur_robust),1) AS max_robust
FROM base
