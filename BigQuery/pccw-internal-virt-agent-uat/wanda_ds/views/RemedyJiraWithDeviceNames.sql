SELECT
  remedy_jira.*, 
  worklog_devices.Device_Names,
  worklog.ExtractedDescription
FROM
  `pccw-internal-virt-agent-uat.wanda_ds.RemedyJira` AS remedy_jira
LEFT JOIN (
  SELECT
    worklog.Incident_Number,
    ARRAY_AGG(DISTINCT ref.shorthand ORDER BY ref.shorthand) AS Device_Names
  FROM
    `pccw-internal-virt-agent-uat.wanda_ds.RemedyWorkLog` AS worklog
  CROSS JOIN
    UNNEST(
      REGEXP_EXTRACT_ALL(
        LOWER(worklog.ExtractedDescription),
        r'(?i)(?:^|[^a-z0-9])([a-z]{2,7}[0-9]{2,3}[.][a-z]{3}[0-9]{2})(?:[.]pccwbtn[.]net)?(?:$|[^a-z0-9.])'
      )
    ) AS device_name_candidate
  JOIN
    `pccw-internal-virt-agent-uat.wanda_ds.device_name_reference` AS ref
  ON
    ref.is_active
    AND ref.shorthand = device_name_candidate
  GROUP BY
    worklog.Incident_Number
) AS worklog_devices
ON
  remedy_jira.Incident_Number = worklog_devices.Incident_Number
LEFT JOIN
  `pccw-internal-virt-agent-uat.wanda_ds.RemedyWorkLog` AS worklog
ON
  remedy_jira.Incident_Number = worklog.Incident_Number;
