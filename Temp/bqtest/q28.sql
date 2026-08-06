WITH remedy_turns AS (
  SELECT d.request_time, d.derived_data,
         ROW_NUMBER() OVER (
           PARTITION BY REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
           ORDER BY d.request_time, d.turn_position
         ) AS rn
  FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
  JOIN (
    SELECT DISTINCT conversation_id
    FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
    WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
      AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  ) r ON r.conversation_id = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
),
lat AS (
  SELECT rn,
    COALESCE(CAST(JSON_VALUE(sm,'$.latency.seconds') AS FLOAT64),0)
      + COALESCE(CAST(JSON_VALUE(sm,'$.latency.nanos') AS FLOAT64),0)/1e9 AS total_sec
  FROM remedy_turns
  CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(derived_data),'$.responseMetrics.stepMetrics')) sm
  WHERE JSON_VALUE(sm,'$.name') = 'runtime.playbook.total_latency'
)
SELECT
  COUNT(*) AS n_requests,
  ROUND(AVG(total_sec),2) AS avg_all_turns_sec,
  ROUND(AVG(IF(rn=1, total_sec, NULL)),2) AS avg_first_prompt_sec,
  ROUND(APPROX_QUANTILES(total_sec,100)[OFFSET(50)],2) AS median_sec,
  ROUND(APPROX_QUANTILES(total_sec,100)[OFFSET(90)],2) AS p90_sec,
  ROUND(APPROX_QUANTILES(total_sec,100)[OFFSET(95)],2) AS p95_sec,
  ROUND(MAX(total_sec),1) AS max_sec
FROM lat
