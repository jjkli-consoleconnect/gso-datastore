WITH base AS (
  SELECT
    conversation_id,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    conversationDuration_sec,
    row_sequential_number
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
turns AS (
  SELECT conversation_id, COUNT(*) AS n_turns
  FROM base GROUP BY conversation_id
)
SELECT
  COUNT(DISTINCT base.conversation_id) AS conversations,
  ROUND(AVG(t.n_turns),2) AS avg_turns_per_conv,
  MAX(t.n_turns) AS max_turns_per_conv,
  ROUND(AVG(IF(base.row_sequential_number=1, base.dur_robust, NULL)),3) AS avg_first_req_dur,
  ROUND(MAX(IF(base.row_sequential_number=1, base.dur_robust, NULL)),1) AS max_first_req,
  ROUND(AVG(base.conversationDuration_sec),3) AS avg_conv_duration_sec,
  ROUND(MAX(base.conversationDuration_sec),1) AS max_conv_dur
FROM base
JOIN turns t ON t.conversation_id = base.conversation_id
