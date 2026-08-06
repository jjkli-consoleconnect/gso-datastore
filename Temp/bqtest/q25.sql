SELECT
  turn_position,
  request_time,
  TO_JSON_STRING(JSON_KEYS(request)) AS req_keys,
  TO_JSON_STRING(JSON_KEYS(response)) AS resp_keys,
  JSON_VALUE(request, '$.receivedTimestamp') AS req_received_ts,
  JSON_VALUE(request, '$.queryParams.timeZone') AS req_tz,
  JSON_VALUE(response, '$.responseTime') AS resp_time,
  TO_JSON_STRING(JSON_KEYS(derived_data)) AS derived_keys,
  ARRAY_LENGTH(JSON_EXTRACT_ARRAY(TO_JSON_STRING(partial_responses))) AS n_partial
FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
WHERE REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') = 'slack-W018FG8L9D5-dm-1984241'
ORDER BY request_time
