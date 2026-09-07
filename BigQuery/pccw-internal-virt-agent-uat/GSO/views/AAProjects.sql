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
    Creator,
    Assignee,
    Component,
    Links,
    SR_Ref,
    SyncTime
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
    ) ORDER BY Transition_Timestamp DESC LIMIT 1)[OFFSET(0)] AS Last_Change,
    
    
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog`
  GROUP BY Issue_Key
),

-- new, calculate in_progress lead time of each tiket
in_progress_calc AS (
  SELECT
    Issue_Key,
    SUM(
      TIMESTAMP_DIFF(
        COALESCE(
          next_transition_timestamp, 
          CASE WHEN current_status = 'In Progress' THEN CURRENT_TIMESTAMP() END
        ),
        transition_timestamp,
        SECOND
      )
    ) AS total_in_progress_seconds
  FROM (
    SELECT
      c.Issue_Key,
      c.Transition_Timestamp AS transition_timestamp,
      c.Transitioned_To,
      t.Status AS current_status,
      LEAD(c.Transition_Timestamp) OVER (
        PARTITION BY c.Issue_Key 
        ORDER BY c.Transition_Timestamp ASC
      ) AS next_transition_timestamp
    FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` c
    LEFT JOIN `pccw-internal-virt-agent-uat.GSO.JiraTickets` t ON t.Key = c.Issue_Key
    WHERE c.Transitioned_To IS NOT NULL
  )
  WHERE Transitioned_To = 'In Progress'
    AND COALESCE(
      next_transition_timestamp, 
      CASE WHEN current_status = 'In Progress' THEN CURRENT_TIMESTAMP() END
    ) IS NOT NULL
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
    t.Creator,
    t.Assignee,
    t.Component,
    ARRAY_TO_STRING(t.Component, ', ') AS Component_Joined,
    t.Links,
    t.SR_Ref,
    t.SyncTime,
    c.Comment_Count,
    c.Last_Comment_At,
    c.Last_Comment.Comment_ID AS Last_Comment_ID,
    c.Last_Comment.Author_Account_ID AS Last_Comment_Author_Account_ID,
    c.Last_Comment.Author_Display_Name AS Last_Comment_Author_Display_Name,
    c.Last_Comment.Created AS Last_Comment_Created,
    c.Last_Comment.Updated AS Last_Comment_Updated,
    c.Last_Comment.Body AS Last_Comment_Body,
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
    ch.Changelog,
    ip.total_in_progress_seconds
  FROM jira_tickets t
  LEFT JOIN comments_agg c ON c.Issue_Key = t.Key
  LEFT JOIN changelog_agg ch ON ch.Issue_Key = t.Key
  LEFT JOIN in_progress_calc ip ON ip.Issue_Key = t.Key
)
SELECT
  j.* EXCEPT(Status, Assignee),
  j.Status AS JiraStatus,
  j.Assignee AS SecondTierAssignee,
  component_unnest AS component_unnest,
  CASE 
    -- Grouped Bug Fixes & Feedback Follow-Ups together
    WHEN component_unnest IN ('Bug Fix', 'Feedback Follow-Up', 'Feedback Followup') 
      THEN 'Bug Fix'

    WHEN component_unnest IN (
      'Documentation', 'Knowledge Management', 'Stakeholder Communication'
    ) 
      THEN 'Documentation'

    WHEN component_unnest IN ('Security & Compliance') 
      THEN 'Compliance'

    WHEN component_unnest IN ('Architecture', 'GCP', 'GWS') 
      THEN 'Infrastructure Enablement'

    WHEN component_unnest IN (
      'Agent Creation', 'Agent Maintenance', 'Agent Update', 'Analytics & Metrics', 
      'Custom Report', 'Data Analysis', 'Data Integration', 'Data Studio', 
      'Looker Studio', 'LookerStudio', 'Event Triggered', 'EventTriggered', 
      'Exploration', 'Google Apps Script', 'Integration', 'System Integration', 
      'New Feature', 'New Function', 'Project Planning', 'Testing', 'TIP'
    ) 
      THEN 'Feature Development/Enhancement'

    WHEN component_unnest IN (
      'Incident Management', 'Change Management', 'Service Performance Management', 
      'Service Request Management', 'Problem Management', 'PagerDuty', 
      'BMC Dashboard', 'BMC Innovation Suite'
    ) 
      THEN 'Operations & Support'

    WHEN component_unnest IN ('0 rows', '', 'Other') OR component_unnest IS NULL 
      THEN '(No Component)'

    ELSE component_unnest
  END AS Allocation,

  -- Project code
  REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') AS ProjectCode,

  -- Jira ticket URL
  CASE WHEN j.Key IS NOT NULL THEN CONCAT('https://consoleconnect.atlassian.net/browse/', j.Key) ELSE NULL END AS JiraURL,

  -- Jira outstanding duration since Created (UTC)
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), DAY)  AS JiraOutstandingDuration_day,
  DATETIME_DIFF(CURRENT_DATETIME('UTC'), DATETIME(j.Created, 'UTC'), HOUR) AS JiraOutstandingDuration_hrs,

  -- Lead time from Jira Created to Resolved (NULL if unresolved)
  TIMESTAMP_DIFF(j.Resolved, j.Created, SECOND) AS LeadTime_secs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, MINUTE) AS LeadTime_mins,
  TIMESTAMP_DIFF(j.Resolved, j.Created, HOUR)   AS LeadTime_hrs,
  TIMESTAMP_DIFF(j.Resolved, j.Created, DAY)    AS LeadTime_days,
  
  --New calculatoin for lead time-->only calculate in progress time
  total_in_progress_seconds as InProgressDuration_secs,
  ROUND(j.total_in_progress_seconds / 60, 2) AS InProgressDuration_mins,
  ROUND(j.total_in_progress_seconds / 3600, 2) AS InProgressDuration_hrs,
  ROUND(j.total_in_progress_seconds / 86400, 2) AS InProgressDuration_days

FROM jira_combined AS j
LEFT JOIN UNNEST(
  IF(
    IFNULL(ARRAY_LENGTH(j.Component), 0) = 0,
    [CAST(NULL AS STRING)],
    ARRAY(
      SELECT TRIM(part)
      FROM UNNEST(j.Component) AS component_item,
           UNNEST(SPLIT(IFNULL(component_item, ''), ',')) AS part
      WHERE NULLIF(TRIM(part), '') IS NOT NULL
    )
  )
) AS component_unnest
WHERE REGEXP_EXTRACT(COALESCE(j.Key, ''), r'^([A-Z]+)') IN ('CCAI','GTA','GDA','GKC')






