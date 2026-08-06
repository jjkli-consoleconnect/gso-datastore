WITH remedy_recent AS (
  SELECT DISTINCT conversation_id
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
remedy_df AS (
  SELECT
    REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)') AS cid,
    ROW_NUMBER() OVER (
      PARTITION BY REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
      ORDER BY d.request_time, d.turn_position
    ) AS rn,
    TIMESTAMP_DIFF(
      TIMESTAMP_SECONDS(CAST(JSON_VALUE(d.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.seconds") AS INT64))
        + INTERVAL CAST(FLOOR(CAST(JSON_VALUE(d.response, "$.queryResult.generativeInfo.actionTracingInfo.actions[1].completeTime.nanos") AS FLOAT64)/1e6) AS INT64) MICROSECOND,
      d.request_time, MICROSECOND
    )/1e6 AS dur_sec
  FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
  JOIN remedy_recent r ON r.conversation_id = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
  WHERE d.request_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  COUNT(DISTINCT cid) AS remedy_conversations,
  COUNT(*) AS remedy_turns,
  ROUND(AVG(IF(rn=1, dur_sec, NULL)),3) AS avg_first_request,
  ROUND(MAX(IF(rn=1, dur_sec, NULL)),1) AS max_first_request,
  ROUND(AVG(IF(rn>1, dur_sec, NULL)),3) AS avg_later_requests,
  ROUND(AVG(dur_sec),3) AS avg_all_turns,
  ROUND(MAX(dur_sec),1) AS max_any_turn
FROM remedy_df
