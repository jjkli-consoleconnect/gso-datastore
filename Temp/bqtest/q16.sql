SELECT
  conversationName,
  REGEXP_EXTRACT(conversationName, r"conversations/([a-zA-Z0-9-_]+)$") AS cid,
  `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName AS hl,
  startTimestamp
FROM `pccw-internal-virtual-agent.wanda_ds.ccai_insights`
WHERE `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName = 'Remedy Ticket'
LIMIT 10
