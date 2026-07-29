CREATE OR REPLACE VIEW `pccw-internal-virtual-agent.wanda_ds.RemedyJiraWithDeviceNames` AS
SELECT
  t1.*,
  t2.Device_Names
FROM
  `pccw-internal-virtual-agent`.`wanda_ds`.`RemedyJira` AS t1
LEFT JOIN (
  SELECT
    Incident_Number,
    ARRAY_AGG(DISTINCT device_name) AS Device_Names
  FROM
    `pccw-internal-virtual-agent`.`wanda_ds`.`RemedyWorkLog`
  CROSS JOIN
    UNNEST( REGEXP_EXTRACT_ALL( ExtractedDescription, r'[A-Za-z]{2,3}[0-9]{2,3}\.[A-Za-z]{2,3}[0-9]{2,3}')) AS device_name
  GROUP BY
    Incident_Number ) AS t2
ON
  t1.Incident_Number = t2.Incident_Number;

