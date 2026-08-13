SELECT table_schema, table_name
FROM `pccw-internal-virt-agent-uat`.`region-europe-west2`.INFORMATION_SCHEMA.TABLES
WHERE table_name LIKE '%billing%' OR table_name LIKE '%export%' OR table_name LIKE '%cost%'
LIMIT 50