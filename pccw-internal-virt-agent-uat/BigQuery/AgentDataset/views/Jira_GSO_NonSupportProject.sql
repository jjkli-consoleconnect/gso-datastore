SELECT
  t.T,
  REGEXP_EXTRACT(t.Key, r'^(\w+)-') AS Project,
  t.Key AS Ticket_Key,
  t.Summary,
  t.Status,
  t.Created,
  t.Updated,
  t.Resolved,
  t.Reporter,
  t.Assignee,
  t.Component,
  t.Resolution,
  CASE
    WHEN LOWER(t.Links) LIKE '%none%' THEN NULL
    ELSE ARRAY_TO_STRING(
           ARRAY(
             SELECT TRIM(link)
             FROM UNNEST(SPLIT(t.Links, ',')) AS link
             WHERE LOWER(TRIM(link)) != 'none' AND TRIM(link) != ''
           ), ', '
         )
  END AS Links_Clean,
  TIMESTAMP_DIFF(t.Resolved, t.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(t.Resolved, t.Created, HOUR) AS LeadTime_hrs,
  TIMESTAMP_DIFF(t.Resolved, t.Created, DAY) AS LeadTime_days,
  t.SyncTime,
  ARRAY(
    SELECT AS STRUCT
      c.Issue_Key,
      c.Comment_ID,
      c.Author_Account_ID,
      c.Author_Display_Name,
      c.Created,
      c.Updated,
      c.Body,
      c.Visibility_Type,
      c.Visibility_Value,
      c.SyncTime,
      c.InsertedAt
    FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` c
    WHERE c.Issue_Key = t.Key
  ) AS Comments,
  ARRAY(
    SELECT AS STRUCT
      ch.Issue_Key,
      ch.History_ID,
      ch.Transition_Timestamp,
      ch.Transitioned_From,
      ch.Transitioned_To,
      ch.Transitioned_By_Account_ID,
      ch.Transitioned_By_Display_Name,
      ch.SyncTime
    FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
    WHERE ch.Issue_Key = t.Key
  ) AS Changelogs,
  

FROM
  `pccw-internal-virt-agent-uat.GSO.JiraTickets` t

WHERE REGEXP_EXTRACT(t.Key, r'^(\w+)-') IN ('CCAI', 'GDA', 'GTA', 'GKC', 'IKM', 'VVT')
