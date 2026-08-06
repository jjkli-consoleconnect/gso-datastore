SELECT
  turn_position,
  request_time,
  JSON_QUERY(derived_data, '$.responseMetrics') AS response_metrics,
  JSON_QUERY(response, '$.queryResult.generativeInfo.actionTracingInfo.actions') AS actions,
  JSON_VALUE(response, '$.queryResult.text') AS response_text,
  JSON_VALUE(response, '$.queryResult.match.matchType') AS match_type
FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
WHERE REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') = 'slack-W018FG8L9D5-dm-1984241'
