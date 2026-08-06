SELECT
  JSON_QUERY(request, '$.queryParams.payload') AS payload,
  JSON_QUERY(conversation_signals, '$') AS conv_signals
FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
WHERE REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') = 'slack-W018FG8L9D5-dm-1984241'
