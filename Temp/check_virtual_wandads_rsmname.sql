SELECT table_name, column_name
FROM `pccw-internal-virtual-agent.wanda_ds.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('RemedyJira', 'RemedyJiraWithDeviceNames', 'RemedyJiraWorkLogView')
  AND column_name = 'RSMName'
ORDER BY table_name;
