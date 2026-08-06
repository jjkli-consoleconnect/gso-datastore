WITH base AS (
  SELECT
    conversation_id,
    requisitionStartTime,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    row_sequential_number
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  COUNT(*) AS rows_30d,
  COUNTIF(row_sequential_number = 1) AS first_req_rows,
  ROUND(AVG(dur_robust),3) AS avg_all_turns,
  ROUND(AVG(IF(row_sequential_number = 1, dur_robust, NULL)),3) AS avg_first_request,
  ROUND(AVG(IF(row_sequential_number > 1, dur_robust, NULL)),3) AS avg_later_requests,
  ROUND(MAX(dur_robust),1) AS max_any_turn
FROM base
