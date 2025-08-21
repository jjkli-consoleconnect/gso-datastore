SELECT
  wl.IncidentNumber,
  hd.Assigned_Group,
  hd.CaseType,
  hd.Categorization_Tier_1,
  wl.WorkLogType,
  wl.WorkLogSubmitDate,
  wl.EffortTimeSpent_mins,
  wl.DescriptionFullName AS DescriptionName,  
  wl.RelevantDescription,
  CASE
    WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) < 7 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 1 Morning'
    WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 7 AND 14 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 2 Afternoon'
    WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 15 AND 22 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 3 Evening'
    ELSE FORMAT_DATE('%Y-%m-%d', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY)) || ' - 1 Morning'
  END AS Shift,
  hd.Cust_ID,
  wl.`DetailedDescription`
FROM
  `pccw-internal-virt-agent-uat.Looker.WorkLog` AS wl
  LEFT JOIN `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd
  ON wl.IncidentNumber = hd.Incident_Number




