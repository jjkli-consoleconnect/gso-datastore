SELECT
  HighlightAgentCleansed,
  COUNT(*) AS n,
  MIN(requisitionStartTime) AS min_req,
  MAX(requisitionStartTime) AS max_req,
  COUNTIF(requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)) AS recent_30d
FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
GROUP BY 1
