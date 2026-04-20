-- RemedyJira: FULL OUTER JOIN of Remedy (T1) and Jira snapshot (T2/T3)

WITH jira_tickets AS (
  SELECT
    T AS Type,
    Project,
    Key,
    Summary,
    Status,
    Created,
    Updated,
    Resolved,
    Reporter,
    Assignee,
    Component,
    RemedyTicketNumber,
    Links,
    SR_Ref,
    SyncTime,
    TimeToFirstResponse_Elapsed,
    TimeToFirstResponse_Goal,
    TimeToFirstResponse_Breached,
    TimeToFirstResponse_Cycles,
    TimeToResolve_Elapsed,
    TimeToResolve_Goal,
    TimeToResolve_Breached,
    TimeToResolve_Cycles,
    TimeToResolution_Elapsed,
    TimeToResolution_Goal,
    TimeToResolution_Breached,
    TimeToResolution_Cycles,
    TimeToApproveNormalChange_Elapsed,
    TimeToApproveNormalChange_Goal,
    TimeToApproveNormalChange_Breached,
    TimeToApproveNormalChange_Cycles,
    ProlongCase_Elapsed,
    ProlongCase_Goal,
    ProlongCase_Breached,
    ProlongCase_Cycles,
    TimeToCloseAfterResolution_Elapsed,
    TimeToCloseAfterResolution_Goal,
    TimeToCloseAfterResolution_Breached,
    TimeToCloseAfterResolution_Cycles,
    AppSupEscalation
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets`
),
comments_agg AS (
  SELECT
    Issue_Key,
    COUNT(*) AS Comment_Count,
    MAX(Created) AS Last_Comment_At,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      Visibility_Type,
      Visibility_Value,
      SyncTime,
      InsertedAt
    ) ORDER BY Created) AS Comments,
    ARRAY_AGG(STRUCT(
      Comment_ID,
      Author_Account_ID,
      Author_Display_Name,
      Created,
      Updated,
      Body,
      Visibility_Type,
      Visibility_Value,
      SyncTime,
      InsertedAt
    ) ORDER BY Created DESC LIMIT 1)[OFFSET(0)] AS Last_Comment
  FROM `pccw-internal-virt-agent-uat.GSO.JiraComments`
  GROUP BY Issue_Key
),
changelog_agg AS (
  SELECT
    Issue_Key,
    COUNT(*) AS Changelog_Count,
    MAX(Transition_Timestamp) AS Last_Transition_At,
    ARRAY_AGG(STRUCT(
      History_ID,
      Transition_Timestamp,
      Transitioned_From,
      Transitioned_To,
      Transitioned_By_Account_ID,
      Transitioned_By_Display_Name,
      SyncTime
    ) ORDER BY Transition_Timestamp) AS Changelog,
    ARRAY_AGG(STRUCT(
      History_ID,
      Transition_Timestamp,
      Transitioned_From,
      Transitioned_To,
      Transitioned_By_Account_ID,
      Transitioned_By_Display_Name,
      SyncTime
    ) ORDER BY Transition_Timestamp DESC LIMIT 1)[OFFSET(0)] AS Last_Change
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog`
  GROUP BY Issue_Key
),
jira_combined AS (
  SELECT
    t.Type,
    t.Project,
    t.Key,
    t.Summary,
    t.Status,
    t.Created,
    t.Updated,
    t.Resolved,
    t.Reporter,
    t.Assignee,
    t.Component,
    ARRAY_TO_STRING(t.Component, ', ') AS Component_Joined,
    t.RemedyTicketNumber,
    ARRAY_TO_STRING(t.RemedyTicketNumber, ', ') AS RemedyTicketNumber_Joined,
    t.Links,
    t.SR_Ref,
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
    c.Comment_Count,
    c.Last_Comment_At,
    c.Last_Comment.Comment_ID AS Last_Comment_ID,
    c.Last_Comment.Author_Account_ID AS Last_Comment_Author_Account_ID,
    c.Last_Comment.Author_Display_Name AS Last_Comment_Author_Display_Name,
    c.Last_Comment.Created AS Last_Comment_Created,
    c.Last_Comment.Updated AS Last_Comment_Updated,
    c.Last_Comment.Body AS Last_Comment_Body,
    c.Last_Comment.Visibility_Type AS Last_Comment_Visibility_Type,
    c.Last_Comment.Visibility_Value AS Last_Comment_Visibility_Value,
    c.Last_Comment.SyncTime AS Last_Comment_SyncTime,
    c.Last_Comment.InsertedAt AS Last_Comment_InsertedAt,
    c.Comments,
    ch.Changelog_Count,
    ch.Last_Transition_At,
    ch.Last_Change.History_ID AS Last_Change_History_ID,
    ch.Last_Change.Transition_Timestamp AS Last_Change_Transition_Timestamp,
    ch.Last_Change.Transitioned_From AS Last_Change_Transitioned_From,
    ch.Last_Change.Transitioned_To AS Last_Change_Transitioned_To,
    ch.Last_Change.Transitioned_By_Account_ID AS Last_Change_Transitioned_By_Account_ID,
    ch.Last_Change.Transitioned_By_Display_Name AS Last_Change_Transitioned_By_Display_Name,
    ch.Last_Change.SyncTime AS Last_Change_SyncTime,
    ch.Changelog
  FROM jira_tickets t
  LEFT JOIN comments_agg c ON c.Issue_Key = t.Key
  LEFT JOIN changelog_agg ch ON ch.Issue_Key = t.Key
)
SELECT
  j.* EXCEPT(Status, Assignee),
  j.Status AS JiraStatus,
  j.Assignee AS SecondTierAssignee,

  -- Project code
  REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') AS ProjectCode,

  -- Project group (Service Delivery vs Center Operations)
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') IN ('GSDT','CCPROV') THEN 'Service Delivery'
    ELSE 'Center Operations'
  END AS Team,

  -- GSOTeam (Jira-only mapping for target projects)
  CASE
    WHEN REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') IN ('GDA','GTA','GKC','CCAI') THEN 'Automation & Analytics'
    ELSE NULL
  END AS GSOTeam,

  -- Jira ticket URL
  CASE WHEN j.Key IS NOT NULL THEN CONCAT('https://consoleconnect.atlassian.net/browse/', j.Key) ELSE NULL END AS JiraURL,

  -- Closed date preference (Jira-only)
  j.Resolved AS ClosedDateCombined,

  -- Jira outstanding duration since Created (UTC)
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), DAY)  AS JiraOutstandingDuration_day,
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), HOUR) AS JiraOutstandingDuration_hrs,

  -- Lead time from Jira Created to Resolved (NULL if unresolved)
  TIMESTAMP_DIFF(j.Resolved, j.Created, SECOND) AS LeadTime_secs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(j.Resolved, j.Created, HOUR)   AS LeadTime_hrs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, DAY)    AS LeadTime_days,

  -- TicketType classification (Jira-only)
  CASE
    WHEN j.Type IN ('Incident','Change','Support Request','Ecosystem Health Check','Proactive Alert','Billing Task','Problem','Sustaining Reliability Engineering','Task','Project','Knowledge Management','Regression Testing','Service Request','Assignment','Service Request with Approvals') THEN CONCAT(REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)'), '-', j.Type)
    ELSE NULL
  END AS TicketType
FROM jira_combined AS j
WHERE REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') IN ('CCAI','GTA','GDA','GKC')





