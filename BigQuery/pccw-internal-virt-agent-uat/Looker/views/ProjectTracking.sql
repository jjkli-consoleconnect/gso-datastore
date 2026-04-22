SELECT 
  T, 
  `Project`, 
  `Key`, 
  Summary, 
  CASE
      WHEN Status = 'Open' THEN '01-Open'
      WHEN Status = 'To Do' THEN '02-To Do'
      WHEN Status = 'TODO' THEN '02-To Do'
      WHEN Status = 'Backlog' THEN '03-Backlog'
      WHEN Status = 'In Progress' THEN '04-In Progress'
      WHEN Status = 'Under review' THEN '05-Under review'
      WHEN Status = 'User Acceptance' THEN '06-User Acceptance'
      WHEN Status = 'Approved' THEN '07-Approved'
      WHEN Status = 'Parked' THEN '08-Parked'
      WHEN Status = 'Done' THEN '09-Done'
      WHEN Status = 'Rejected' THEN '10-Rejected'
      WHEN Status = 'Cancelled' THEN '11-Cancelled'
      ELSE Status
  END AS StatusSorted,
  Status,
  Created, 
  Updated, 
  Resolved, 
  Reporter, 
  Assignee,
  TIMESTAMP_DIFF(Resolved, Created, MINUTE) AS Leadtime,
  CASE
      WHEN Project = 'Google Contact Center AI Solution' THEN 'CCAI'
      WHEN Project = 'GS&O Knowledge Consolidation' THEN 'GKC'
      WHEN Project = 'GS&O Data Analytics' THEN 'GDA'
      WHEN Project = 'GS&O Tool Automation' THEN 'GTA'
      ELSE NULL
  END AS ProjectCode,
  Component,
  SyncTime

FROM 
  `pccw-internal-virt-agent-uat.JIRAProjects.ProjectTracking`
LEFT JOIN UNNEST(Component) AS Component

WHERE 
  CASE
      WHEN Project = 'Google Contact Center AI Solution' THEN 'CCAI'
      WHEN Project = 'GS&O Knowledge Consolidation' THEN 'GKC'
      WHEN Project = 'GS&O Data Analytics' THEN 'GDA'
      WHEN Project = 'GS&O Tool Automation' THEN 'GTA'
      ELSE NULL
  END IS NOT NULL 

ORDER BY updated desc

