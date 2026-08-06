SELECT
  COUNT(*) AS remedy_conversations,
  ROUND(AVG(durationNanos/1e9),1) AS avg_conv_duration_sec,
  ROUND(APPROX_QUANTILES(durationNanos/1e9,100)[OFFSET(50)],1) AS p50,
  ROUND(APPROX_QUANTILES(durationNanos/1e9,100)[OFFSET(90)],1) AS p90,
  ROUND(MAX(durationNanos/1e9),1) AS max
FROM `pccw-internal-virtual-agent.wanda_ds.ccai_insights`
WHERE DATE(startTimestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName
      IN ('Remedy Ticket','Remedy Ticket Agent','Check status')
