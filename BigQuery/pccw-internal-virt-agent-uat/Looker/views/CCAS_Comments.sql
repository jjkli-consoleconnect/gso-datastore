WITH parsed_links AS (
  SELECT 
    *, 
    (
      SELECT STRING_AGG(
        COALESCE(
          JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), 
          JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')
        ), ','
      ) 
      FROM UNNEST(JSON_EXTRACT_ARRAY(Links, '$')) AS link
    ) AS linkedkeys
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCAS`
),

user_details AS (
  SELECT DISTINCT 
    u.jiraID, 
    u.FullName, 
    u.Team, 
    u.Title
  FROM `pccw-internal-virt-agent-uat.RemedyICS.UserID` u
),

comments_with_user_details AS (
  SELECT 
    c.Issue_Key, 
    c.Comment_ID, 
    c.Author_Account_ID, 
    CASE 
      WHEN u.FullName IS NULL THEN c.Author_Display_Name 
      ELSE u.FullName 
    END AS Commenter,
    COALESCE(u.Team, 'Unknown') AS Commenter_Group,
    COALESCE(u.Title, 'Unknown') AS Commenter_Title,
    c.Created AS Comment_Created, 
    c.Updated AS Comment_Updated, 
    c.Body AS Comment_Body, 
    c.Visibility_Type AS Comment_Visibility_Type, 
    c.Visibility_Value AS Comment_Visibility_Value
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCAS_comments` c
  LEFT JOIN user_details u ON c.Author_Display_Name = u.FullName 
)

SELECT 
  c.*, 
  p.*, 
  p.Remedy_Ticket_Number AS RemedyTicketNumber, 
  TIMESTAMP_DIFF(p.Resolved, p.Created, MINUTE)/60 AS Leadtime_hrs, 
  TIMESTAMP_DIFF(p.Resolved, p.Created, MINUTE)/60/24 AS Leadtime_days, 
  u3.FullName AS Creator_FullName, 
  COALESCE(u3.Team, u1.Team) AS Creator_Group, 
  u3.Title AS Creator_Title, 
  u2.FullName AS Reporter_FullName, 
  u2.Team AS Reporter_Group, 
  u2.Title AS Reporter_Title, 
  u1.FullName AS Assignee_FullName, 
  u1.Team AS Assignee_Group, 
  u1.Title AS Assignee_Title, 

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

  p.SLA_Ongoing_elapsedTime_millis /60000 AS `SLA_Ongoing_elapsedTime_min`, 
  p.SLA_Ongoing_remainingTime_millis /60000 AS `SLA_Ongoing_remainingTime_min`

FROM comments_with_user_details c
LEFT JOIN parsed_links p ON c.Issue_Key = p.`Key`
LEFT JOIN user_details u1 ON p.Assignee = u1.jiraID
LEFT JOIN user_details u2 ON p.Reporter = u2.jiraID
LEFT JOIN user_details u3 ON p.Creator = u3.jiraID OR p.Creator = u3.FullName
