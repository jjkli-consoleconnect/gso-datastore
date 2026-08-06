SELECT
  COUNT(*) AS rows_30d,
  COUNTIF(requisitionDuration_sec IS NULL) AS null_rows,
  COUNTIF(requisitionDuration_sec = 0) AS zero_rows,
  COUNTIF(requisitionDuration_sec <= 0.1) AS tiny_rows_le_0p1,
  ROUND(AVG(requisitionDuration_sec),3) AS avg_incl_zeros,
  ROUND(AVG(IF(requisitionDuration_sec > 0.1, requisitionDuration_sec, NULL)),3) AS avg_excl_tiny
FROM `pccw-internal-virtual-agent.LookerStudio.CCAI_Dialogflow`
WHERE HighlightAgentCleansed = 'Remedy Ticket Agent'
  AND requisitionStartTime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
