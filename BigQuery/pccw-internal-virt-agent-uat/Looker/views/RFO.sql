SELECT
  hd.`Assigned_Group` AS `NOC`,
  hd.`Incident_Number`,
  hd.`Closed_Date`,
  CASE 
        WHEN lower(hd.`Fault_Cause`) LIKE '%no fault found%' THEN 'No Fault Found'
        WHEN lower(hd.`Fault_Cause`) LIKE '%operation ticket%' THEN 'Operation Ticket'
        WHEN lower(hd.`Fault_Cause`) LIKE '%other%' THEN 'Other'
        ELSE hd.`Fault_Cause`
  END AS `Fault_Cause`,
  CASE WHEN lower(hd.`Fault_Cause`) LIKE '%no fault found%' THEN 1 ELSE NULL END AS `NFF`,
  CASE WHEN lower(hd.`Fault_Cause`) LIKE '%operation ticket%' THEN 1 ELSE NULL END AS `Operation_Ticket`,
  CASE WHEN lower(hd.`Fault_Cause`) LIKE '%other%' THEN 1 ELSE NULL END AS `Others`,
  hd.`Closed_By` AS Fullname


FROM
    `pccw-internal-virt-agent-uat.Looker.helpdesk` hd


WHERE 
    hd.`casetype` = 'Incident' 
    And hd.`Status` = 'Closed'



ORDER BY `Closed_Date` DESC

