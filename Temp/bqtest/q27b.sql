WITH remedy_recent AS (
  SELECT DISTINCT conversation_id
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
lat AS (
  SELECT
    JSON_VALUE(sm, '$.name') AS step_name,
    COALESCE(CAST(JSON_VALUE(sm,'$.latency.seconds') AS FLOAT64),0)
      + COALESCE(CAST(JSON_VALUE(sm,'$.latency.nanos') AS FLOAT64),0)/1e9 AS secs
  FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
  JOIN remedy_recent r ON r.conversation_id = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
  CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(TO_JSON_STRING(d.derived_data), '$.responseMetrics.stepMetrics')) AS sm
)
SELECT
  COUNTIF(step_name='runtime.playbook.total_latency') AS n_total,
  ROUND(AVG(IF(step_name='runtime.playbook.total_latency',secs,NULL)),3) AS avg_total,
  ROUND(APPROX_QUANTILES(IF(step_name='runtime.playbook.total_latency',secs,NULL),100)[OFFSET(90)],2) AS p90_total,
  ROUND(MAX(IF(step_name='runtime.playbook.total_latency',secs,NULL)),1) AS max_total,
  ROUND(AVG(IF(step_name='runtime.playbook.llm_latency',secs,NULL)),3) AS avg_llm,
  ROUND(MAX(IF(step_name='runtime.playbook.llm_latency',secs,NULL)),1) AS max_llm,
  ROUND(AVG(IF(step_name='runtime.playbook.tool_latency',secs,NULL)),3) AS avg_tool,
  ROUND(APPROX_QUANTILES(IF(step_name='runtime.playbook.tool_latency',secs,NULL),100)[OFFSET(90)],2) AS p90_tool,
  ROUND(MAX(IF(step_name='runtime.playbook.tool_latency',secs,NULL)),1) AS max_tool
FROM lat
