SELECT
  conversation_name,
  REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') AS session_id,
  request_time,
  turn_position
FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
WHERE REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') = 'slack-W018FH1FHPH-dm-1950192'
ORDER BY request_time
LIMIT 10
