SELECT
  JSON_VALUE(request, '$.queryParams.sessionInfo.parameters.slack_message_ts') AS slack_message_ts,
  JSON_VALUE(request, '$.queryParams.sessionInfo.parameters.slack_thread_ts') AS slack_thread_ts,
  JSON_QUERY(request, '$.queryParams.sessionInfo') AS session_info,
  JSON_VALUE(request, '$.queryParams.payload.data.ts') AS payload_ts,
  request_time
FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
WHERE REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') = 'slack-W018FG8L9D5-dm-1984241'
