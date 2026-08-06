WITH base AS (
  SELECT
    conversation_id,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    conversationDuration_sec,
    row_sequential_number
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  COUNT(DISTINCT conversation_id) AS conversations,
  COUNT(*) AS rows_30d,
  ROUND(AVG(IF(row_sequential_number=1, dur_robust, NULL)),3) AS avg_first_req_dur,
  ROUND(MAX(IF(row_sequential_number=1, dur_robust, NULL)),1) AS max_first_req,
  ROUND(AVG(conversationDuration_sec),3) AS avg_conv_duration_sec,
  ROUND(MAX(conversationDuration_sec),1) AS max_conv_dur
FROM base
