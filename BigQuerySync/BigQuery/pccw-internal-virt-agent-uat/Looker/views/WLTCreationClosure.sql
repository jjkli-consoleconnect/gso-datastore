WITH HelpDeskWithShifts AS (
  SELECT
    hd.`Incident_Number` AS Incident_Number,
    hd.`Submit_Date` AS Submit_Date,
    hd.`Closed_Date` AS Closed_Date,
    hd.`Assigned_Group` AS NOC,
    hd.`Status` AS Status,
    hd.`CaseType` AS CaseType,
    hd.Submitter AS OpenedBy_FullName,
    hd.Closed_By AS ClosedBy_FullName,
    CASE
      WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 0 AND 6 THEN FORMAT_DATE('%Y-%m-%d', hd.Submit_Date) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 7 AND 14 THEN FORMAT_DATE('%Y-%m-%d', hd.Submit_Date) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 15 AND 22 THEN FORMAT_DATE('%Y-%m-%d', hd.Submit_Date) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 23 AND 23 THEN FORMAT_DATE('%Y-%m-%d', hd.Submit_Date) || ' - 1 Morning'
      ELSE FORMAT_DATE('%Y-%m-%d', DATE_ADD(hd.Submit_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS ShiftCreation,
    CASE
      WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 0 AND 6 THEN FORMAT_DATE('%Y-%m-%d', hd.Closed_Date) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 7 AND 14 THEN FORMAT_DATE('%Y-%m-%d', hd.Closed_Date) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 15 AND 22 THEN FORMAT_DATE('%Y-%m-%d', hd.Closed_Date) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 23 AND 23 THEN FORMAT_DATE('%Y-%m-%d', hd.Closed_Date) || ' - 1 Morning'
      ELSE FORMAT_DATE('%Y-%m-%d', DATE_ADD(hd.Closed_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS ShiftClosure
  FROM
    `pccw-internal-virt-agent-uat.Looker.helpdesk` hd
), WLT AS (
  SELECT
    hd.Incident_Number,
    hd.Assigned_Group,
    hd.CaseType,
    hd.Categorization_Tier_1,
    wl.WorkLogType,
    wl.WorkLogSubmitDate,
    wl.EffortTimeSpent_mins,
    wl.`DescriptionFullName` AS DescriptionName,
    CASE
      WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 0 AND 6 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 7 AND 14 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 15 AND 22 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 23 AND 23 THEN FORMAT_DATE('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 1 Morning'
      ELSE FORMAT_DATE('%Y-%m-%d', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS Shift
  FROM
    `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd
    INNER JOIN `pccw-internal-virt-agent-uat.Looker.WorkLog` AS wl
    ON hd.Incident_Number = wl.IncidentNumber
)
SELECT
  wlt.WorkLogType,
  wlt.WorkLogSubmitDate,
  wlt.DescriptionName,
  wlt.EffortTimeSpent_mins,
  wlt.Shift,
  wlt.Incident_Number,
  hds.Submit_Date,
  hds.OpenedBy_FullName,
  hds.Closed_Date,
  hds.ClosedBy_FullName,
  hds.NOC,
  hds.Status,
  hds.CaseType,
  hds.ShiftCreation,
  hds.ShiftClosure
FROM
  WLT wlt
LEFT JOIN HelpDeskWithShifts hds ON wlt.Incident_Number = hds.Incident_Number
ORDER BY
  wlt.Incident_Number,
  wlt.WorkLogSubmitDate,
  wlt.Shift;

