SELECT column_name, data_type
FROM `pccw-internal-virtual-agent.wanda_ds.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'dialogflow_bigquery_export_data'
ORDER BY ordinal_position
