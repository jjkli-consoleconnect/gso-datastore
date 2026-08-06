WITH remedy_conv AS (
  SELECT DISTINCT REGEXP_EXTRACT(conversationName, r"conversations/([a-zA-Z0-9-_]+)$") AS cid
  FROM `pccw-internal-virtual-agent.wanda_ds.ccai_insights`
  WHERE `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName = 'Remedy Ticket'
)
SELECT
  (SELECT MAX(request_time) FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`) AS df_max_request,
  (SELECT COUNT(*) FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data`
     WHERE request_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)) AS df_recent_rows,
  (SELECT MAX(d.request_time)
     FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
     JOIN remedy_conv rc ON rc.cid = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')) AS remedy_df_max_request,
  (SELECT COUNT(*)
     FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
     JOIN remedy_conv rc ON rc.cid = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')) AS remedy_df_all_time_rows
