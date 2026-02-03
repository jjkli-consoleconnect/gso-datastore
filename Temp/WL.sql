SELECT  
  wl.`Incident Number` AS IncidentNumber,  
  wl.`Work Log Type` AS WorkLogType,  
  wl.`Work Log ID` AS WorkLogID,  
  wl.`Work Log Submit Date` AS WorkLogSubmitDate,  
  CASE  
    WHEN cp_sub.`Full Name` IS NOT NULL THEN cp_sub.`Full Name`  
    ELSE wl.`Work Log Submitter`  
  END AS WorkLogSubmitter,  
  wl.`Last Modified Date` AS LastModifiedDate, 
  CASE  
    WHEN cp_mod.`Full Name` IS NOT NULL THEN cp_mod.`Full Name`  
    ELSE wl.`Last Modified By`  
  END AS LastModifiedBy,
  SUBSTR(
    wl.`Detailed Description`,
    -- start just after '---'
    CHARINDEX('---', wl.`Detailed Description`, 1)
      + LENGTH('---'),
    -- length = position of 'wrote:' minus our start pos
    CHARINDEX(
      'wrote:',
      wl.`Detailed Description`,
      CHARINDEX('---', wl.`Detailed Description`, 1)
        + LENGTH('---')
    )
      - (
        CHARINDEX('---', wl.`Detailed Description`, 1)
          + LENGTH('---')
      )
  ) AS ExtractedDescription

FROM `HPD:WorkLog` wl  
LEFT JOIN `HPD:Help Desk` hd ON wl.`Incident Number` = hd.`Incident Number`  
LEFT JOIN `CTM:People` cp_sub ON wl.`Work Log Submitter` = cp_sub.`Remedy Login ID`  
LEFT JOIN `CTM:People` cp_mod ON wl.`Last Modified By` = cp_mod.`Remedy Login ID`  

WHERE wl.`Last Modified Date` BETWEEN $__from/1000 AND $__to/1000
  AND hd.`Assigned Group` IN ($assignedgroup)
  AND wl.`Work Log Type` NOT IN ('Assignment Change', '---NOC Selection---', 'Internal Escalation')
  AND wl.`Detailed Description` NOT LIKE 'Ticket Escalated Notification%'
  AND wl.`Detailed Description` NOT LIKE 'Escalated to Manager%'
  AND wl.`Detailed Description` NOT LIKE 'Ticket Creation Notification%'
  AND wl.`Detailed Description` NOT LIKE 'Ticket Closure Notification%'



    
ORDER BY WorkLogSubmitDate DESC