WITH remedy_conv AS (
  SELECT DISTINCT REGEXP_EXTRACT(conversationName, r"conversations/([a-zA-Z0-9-_]+)$") AS cid
  FROM `pccw-internal-virtual-agent.wanda_ds.ccai_insights`
  WHERE `sentences`[SAFE_OFFSET(0)].`highlightData`[SAFE_OFFSET(0)].displayName = 'Remedy Ticket'
),
remedy_df AS (
  SELECT
    REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)') AS cid
  FROM `pccw-internal-virtual-agent.wanda_ds.dialogflow_bigquery_export_data` d
  JOIN remedy_conv rc ON rc.cid = REGEXP_EXTRACT(d.conversation_name, r'sessions/([^/]+)')
  WHERE d.request_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT
  (SELECT COUNT(*) FROM remedy_conv) AS remedy_conv_ids,
  (SELECT COUNT(*) FROM remedy_df) AS matched_df_rows,
  (SELECT FORMAT_TIMESTAMP('%F %T', CURRENT_TIMESTAMP())) AS bq_now_utc
