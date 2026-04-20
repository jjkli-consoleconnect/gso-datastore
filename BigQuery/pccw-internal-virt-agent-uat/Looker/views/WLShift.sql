SELECT
 Incident_Number,
 NOC,
 Status,
 CaseType,
 Shift,
 NULL AS Work_Log_Type,
 NULL AS DescriptionFullName,
 NULL AS Effort_Time_Spent,
 FullName AS Creation_FullName,
 NULL AS Closure_FullName,
 Submit_Date AS Date,
 DoW

FROM (
 SELECT
   hd.`Incident_Number` AS Incident_Number,
   hd.`Assigned_Group` AS NOC,
   hd.`Status` AS Status,
   hd.`CaseType` AS CaseType,
   hd.Submitter AS FullName,
   CASE
     WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 1 Morning'
     WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 2 Afternoon'
     WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 3 Evening'
     WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(hd.Submit_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
     ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(hd.Submit_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
   END AS Shift,
   hd.Submit_Date AS Submit_Date,
   CASE
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', hd.Submit_Date)
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', hd.Submit_Date)
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', hd.Submit_Date)
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(hd.Submit_Date, INTERVAL 1 DAY))
        ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(hd.Submit_Date, INTERVAL 1 DAY))
    END AS DoW
 FROM
   `pccw-internal-virt-agent-uat.Looker.helpdesk` hd
) AS creation


UNION ALL


SELECT
 Incident_Number,
 NOC,
 Status,
 CaseType,
 Shift,
 NULL AS Work_Log_Type,
 NULL AS Work_Log_Submitter,
 NULL AS Effort_Time_Spent,
 NULL AS Creation_FullName,
 FullName AS Closure_FullName,
 Closed_Date AS Date,
 DoW
FROM (
 SELECT
   hd.`Incident_Number` AS Incident_Number,
   hd.`Assigned_Group` AS NOC,
   hd.`Status` AS Status,
   hd.`CaseType` AS CaseType,
   hd.Closed_By AS FullName,
   CASE
     WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 1 Morning'
     WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 2 Afternoon'
     WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 3 Evening'
     WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(hd.Closed_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
     ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(hd.Closed_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
   END AS Shift,
   hd.Closed_Date AS Closed_Date,
   CASE
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', hd.Closed_Date)
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', hd.Closed_Date)
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', hd.Closed_Date)
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(hd.Closed_Date, INTERVAL 1 DAY))
        ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(hd.Closed_Date, INTERVAL 1 DAY))
    END AS DoW
 FROM
   `pccw-internal-virt-agent-uat.Looker.helpdesk` hd
 WHERE
   hd.Closed_Date IS NOT NULL
) AS closure


UNION ALL


SELECT
 Incident_Number,
 NOC,
 Status,
 CaseType,
 Shift,
 WorkLogType AS Work_Log_Type,
 DescriptionFullName AS Work_Log_Submitter,
 EffortTimeSpent_mins AS Effort_Time_Spent,
 NULL AS Creation_FullName,
 NULL AS Closure_FullName,
 WorkLogSubmitDate AS Date,
 DoW
FROM (
 SELECT
   wl.IncidentNumber AS Incident_Number,
   hd.Assigned_Group AS NOC,
   hd.Status AS Status,
   hd.CaseType AS CaseType,
   CASE
     WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 1 Morning'
     WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 2 Afternoon'
     WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLogSubmitDate) || ' - 3 Evening'
     WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY)) || ' - 1 Morning'
     ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY)) || ' - 1 Morning'
   END AS Shift,
   wl.WorkLogType,
   wl.DescriptionFullName,
   wl.EffortTimeSpent_mins,
   wl.WorkLogSubmitDate,
   CASE
        WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', wl.WorkLogSubmitDate)
        WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', wl.WorkLogSubmitDate)
        WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', wl.WorkLogSubmitDate)
        WHEN EXTRACT(HOUR FROM wl.WorkLogSubmitDate) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY))
        ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(wl.WorkLogSubmitDate, INTERVAL 1 DAY))
    END AS DoW
 FROM
   `pccw-internal-virt-agent-uat.Looker.WorkLog` wl
 LEFT JOIN
   `pccw-internal-virt-agent-uat.Looker.helpdesk` AS hd
   ON wl.IncidentNumber = hd.Incident_Number
 WHERE
   wl.WorkLogSubmitDate IS NOT NULL
) AS work_logs


ORDER BY
 Shift DESC




