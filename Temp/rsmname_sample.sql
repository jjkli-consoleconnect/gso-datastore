SELECT Incident_Number, RSMName
FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`
WHERE RSMName IS NOT NULL AND TRIM(CAST(RSMName AS STRING)) != ''
LIMIT 10;
