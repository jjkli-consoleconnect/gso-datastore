WITH base AS (
  SELECT
    conversation_id,
    requisitionDuration_sec AS dur_hardcoded,
    TIMESTAMP_DIFF(action_2_complete_timestamp, requisitionStartTime, MICROSECOND)/1e6 AS dur_robust,
    conversationDuration_sec,
    row_sequential_number,
    requisitionStartTime
  FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
  WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
    AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
turns AS (
  SELECT conversation_id, COUNT(*) AS n_turns
  FROM base GROUP BY conversation_id
)
SELECT
  (SELECT COUNT(DISTINCT conversation_id) FROM base) AS conversations,
  (SELECT ROUND(AVG(n_turns),2) FROM turns) AS avg_turns_per_conv,
  (SELECT ROUND(MAX(n_turns),0) FROM turns) AS max_turns_per_conv,
  (SELECT ROUND(AVG(dur_robust),3) FROM base WHERE row_sequential_number=1) AS avg_first_req_dur,
  (SELECT ROUND(APPROX_QUANTILES(dur_robust,100)[OFFSET(90)],3) FROM base WHERE row_sequential_number=1) AS p90_first_req,
  (SELECT ROUND(MAX(dur_robust),1) FROM base WHERE row_sequential_number=1) AS max_first_req,
  (SELECT ROUND(AVG(conversationDuration_sec),3) FROM base) AS avg_conv_duration_sec,
  (SELECT ROUND(APPROX_QUANTILES(conversationDuration_sec,100)[OFFSET(50)],1) FROM base) AS p50_conv_dur,
  (SELECT ROUND(APPROX_QUANTILES(conversationDuration_sec,100)[OFFSET(90)],1) FROM base) AS p90_conv_dur,
  (SELECT ROUND(MAX(conversationDuration_sec),1) FROM base) AS max_conv_dur
