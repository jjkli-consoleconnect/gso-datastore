SELECT
  RemedyJira.*,
  RemedyWorkLog.ExtractedDescription
FROM
  `pccw-internal-virt-agent-uat`.`wanda_ds`.`RemedyJira` AS RemedyJira
LEFT JOIN
  `pccw-internal-virt-agent-uat`.`wanda_ds`.`RemedyWorkLog` AS RemedyWorkLog
ON
  RemedyJira.Incident_Number = RemedyWorkLog.Incident_Number
