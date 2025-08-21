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
  t.RemedyTicketNumber,
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
  CASE
    WHEN LOWER(t.Links) LIKE '%none%' THEN NULL
    ELSE ARRAY(
            SELECT TRIM(t.Links)
            FROM UNNEST(SPLIT(t.Links, ',')) AS link
            WHERE LOWER(TRIM(t.Links)) != 'none' AND TRIM(t.Links) != ''
        )
  END AS Links_Clean_Array,
  ARRAY(
    SELECT DISTINCT REGEXP_EXTRACT(TRIM(link), r'^(\w+)-')
    FROM UNNEST(SPLIT(t.Links, ',')) AS link
    WHERE
      LOWER(TRIM(link)) != 'none'
      AND TRIM(link) != ''
      AND REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') IS NOT NULL
  ) AS LinkedProject,
  -- Array of all project prefixes from links, excluding self-links
  ARRAY(
    SELECT DISTINCT proj
    FROM (
      SELECT REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') AS proj
      FROM UNNEST(SPLIT(t.Links, ',')) AS link
      WHERE
        LOWER(TRIM(link)) != 'none'
        AND TRIM(link) != ''
        AND REGEXP_EXTRACT(TRIM(link), r'^(\w+)-') IS NOT NULL
    )
    WHERE proj != REGEXP_EXTRACT(t.Key, r'^(\w+)-')
  ) AS LinkedProject_Clean,
  t.SR_Ref,
  TIMESTAMP_DIFF(t.Resolved, t.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(t.Resolved, t.Created, HOUR) AS LeadTime_hrs,
  TIMESTAMP_DIFF(t.Resolved, t.Created, DAY) AS LeadTime_days,
  t.SyncTime,
  t.TimeToFirstResponse_Elapsed,
  t.TimeToFirstResponse_Goal,
  t.TimeToFirstResponse_Breached,
  t.TimeToFirstResponse_Cycles,
  t.TimeToResolve_Elapsed,
  t.TimeToResolve_Goal,
  t.TimeToResolve_Breached,
  t.TimeToResolve_Cycles,
  t.TimeToResolution_Elapsed,
  t.TimeToResolution_Goal,
  t.TimeToResolution_Breached,
  t.TimeToResolution_Cycles,
  t.TimeToApproveNormalChange_Elapsed,
  t.TimeToApproveNormalChange_Goal,
  t.TimeToApproveNormalChange_Breached,
  t.TimeToApproveNormalChange_Cycles,
  t.ProlongCase_Elapsed,
  t.ProlongCase_Goal,
  t.ProlongCase_Breached,
  t.ProlongCase_Cycles,
  t.TimeToCloseAfterResolution_Elapsed,
  t.TimeToCloseAfterResolution_Goal,
  t.TimeToCloseAfterResolution_Breached,
  t.TimeToCloseAfterResolution_Cycles,
  t.AppSupEscalation,
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
  -- Array of all project prefixes from links
  

FROM
  `pccw-internal-virt-agent-uat.GSO.JiraTickets` t

