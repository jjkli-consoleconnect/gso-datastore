SELECT COUNTIF(RSMName IS NOT NULL AND TRIM(CAST(RSMName AS STRING)) != '') AS rsmname_populated_rows
FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`;
