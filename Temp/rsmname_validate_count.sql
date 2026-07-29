SELECT
  COUNTIF(RSMName IS NOT NULL AND TRIM(CAST(RSMName AS STRING)) != '' AND STRPOS(RSMName, ',') > 0) AS malformed_rows_remaining,
  COUNTIF(RSMName IS NOT NULL AND TRIM(CAST(RSMName AS STRING)) != '') AS populated_rows
FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`;
