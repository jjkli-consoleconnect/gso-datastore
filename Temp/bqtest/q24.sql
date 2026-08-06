SELECT conversation_id, requisitionStartTime
FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
  AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY requisitionStartTime DESC
LIMIT 1
