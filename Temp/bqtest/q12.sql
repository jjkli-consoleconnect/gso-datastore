SELECT conversation_id, row_sequential_number, raw_turn_position
FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
  AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
LIMIT 5
