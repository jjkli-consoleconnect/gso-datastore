SELECT
  `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName AS hl,
  COUNT(*) AS n
FROM `pccw-internal-virtual-agent.wanda_ds.ccai_insights`
GROUP BY 1
ORDER BY n DESC
LIMIT 40
