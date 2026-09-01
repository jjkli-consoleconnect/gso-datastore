WITH parsed_links AS (
  SELECT 
    *,
    (
      SELECT STRING_AGG(
        COALESCE(
          JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'),
          JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')
        ), 
        ','
      ) 
      FROM UNNEST(JSON_EXTRACT_ARRAY(Links, '$')) AS link
    ) AS linkedkeys
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCAS`
),
user_details AS (
  SELECT 
    DISTINCT u.jiraID, u.FullName, u.Team, u.Title
  FROM `pccw-internal-virt-agent-uat.RemedyICS.UserID` u
)

SELECT
  p.Type AS `T`,
  p.Priority, 
  p.`Key`, 
  p.Summary,
  p.Status,
  p.Created, 
  p.Updated, 
  p.Resolved, 
  p.Assignee, 
  CASE 
    WHEN u1.FullName IS NOT NULL THEN u1.FullName  
    ELSE p.Assignee  
  END AS Assignee_FullName,
  u1.Team AS Assignee_Group,
  u1.Title AS Assignee_Title,
  p.Task_Definition AS TaskDefinition, 
  p.Console_Service AS ConsoleService, 
  p.Port_Prov_Status AS PortProvStatus, 
  p.Remedy_Ticket_Number AS RemedyTicketNumber,
  TIMESTAMP_DIFF(p.Resolved, p.Created, HOUR) AS Leadtime_hrs,
  TIMESTAMP_DIFF(p.Resolved, p.Created, DAY) AS Leadtime_days,
  p.Creator, 
  CASE WHEN u3.FullName IS NULL THEN p.Creator ELSE u2.FullName END AS Creator_FullName,
  COALESCE(u3.Team, u1.Team, u2.Team) AS Creator_Group,
  u3.Title AS Creator_Title,
  p.Components, 
  p.Labels, 
  p.Handover_Instruction, 
  p.Handover_Report_AS, 
  p.Resolution, 
  p.Resolution_Time, 
  p.First_Response, 
  p.Reporter, 
  CASE WHEN u2.FullName IS NULL THEN p.Reporter ELSE u2.FullName END AS Reporter_FullName,
  u2.Team AS Reporter_Group,
  u2.Title AS Reporter_Title,
  p.Request_Type, 
  p.linkedkeys,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^CCSUP(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS CCSUPSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^SLSUP(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS SLSUPSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^CCONB(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS CCONBSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^COPS(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS COPSSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^CSCM(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS CSCMSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^TAC(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS TACSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^CCT4(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS CCT4Solved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^SH(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS SHSolved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^AS3491(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS AS3491Solved,
  CASE
    WHEN EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^TCM(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS TCMSolved,
  CASE
    WHEN p.Links IS NULL THEN p.`Key`
    WHEN NOT EXISTS(
      SELECT 1 
      FROM UNNEST(JSON_EXTRACT_ARRAY(p.Links, '$')) AS link
      WHERE REGEXP_CONTAINS(COALESCE(JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')), r'^(CCSUP|SLSUP|CCONB|COPS|CSCM|CCT4|SH|AS3491)(-\d+)?$')
    ) THEN p.`Key`
    ELSE NULL
  END AS CCASSolved,
  p.Date_ordered,
  p.SLA_Ongoing_StartTime_jira, 
  p.SLA_Ongoing_BreachTime_jira, 
  p.SLA_Ongoing_Breached, 
  p.SLA_Ongoing_elapsedTime_millis /60000 AS `SLA_Ongoing_elapsedTime_min`,
  p.SLA_Ongoing_remainingTime_millis /60000 AS `SLA_Ongoing_remainingTime_min`
FROM
  parsed_links p

LEFT JOIN user_details u1 ON p.Assignee = u1.jiraID
LEFT JOIN user_details u2 ON p.Reporter = u2.jiraID
LEFT JOIN user_details u3 ON COALESCE(u1.FullName, p.Assignee) = u3.FullName
