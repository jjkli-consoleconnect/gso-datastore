WITH base AS (
  SELECT
    conversation_id,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    row_sequential_number
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
)
SELECT
  COUNT(*) AS rows_1d,
  ROUND(AVG(IF(row_sequential_number=1, dur_robust, NULL)),3) AS avg_first_req_dur,
  ROUND(MAX(IF(row_sequential_number=1, dur_robust, NULL)),1) AS max_first_req,
  ROUND(AVG(IF(row_sequential_number>1, dur_robust, NULL)),3) AS avg_later_req_dur,
  ROUND(MAX(dur_robust),1) AS max_any_turn_dur
FROM base
