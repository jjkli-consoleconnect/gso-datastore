-- MSS Jira combined snapshot optimized for Looker Studio and ticket-centric analytics.
-- Grain: 1 row per ticket (no fan-out). Comments and Changelog are pre-aggregated 1:1 per ticket
-- and provided as: (a) convenient summary columns (counts, latest) and (b) full arrays of structs.

WITH t AS (
  SELECT
    T,
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
    Service,
    Origin,
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
  WHERE COALESCE(IsDeleted, FALSE) = FALSE
    AND (
      COALESCE(Project, '') = 'Managed Security Services'
      OR REGEXP_CONTAINS(COALESCE(Key, ''), r'^MSS-')
    )
),
c_all AS (
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
  WHERE REGEXP_CONTAINS(COALESCE(Issue_Key, ''), r'^MSS-')
  GROUP BY Issue_Key
),
c_first AS (
  SELECT
    c.Issue_Key,
    COALESCE(
      (
        SELECT AS STRUCT
          comment.Created AS FirstResponse_At,
          comment.Author_Display_Name AS FirstResponse_By,
          'comment-derived: first public non-reporter comment' AS FirstResponse_Source
        FROM UNNEST(c.Comments) AS comment
        WHERE COALESCE(comment.Author_Display_Name, '') != COALESCE(t.Reporter, '')
          AND comment.Visibility_Type IS NULL
          AND comment.Visibility_Value IS NULL
        ORDER BY comment.Created
        LIMIT 1
      ),
      (
        SELECT AS STRUCT
          comment.Created AS FirstResponse_At,
          comment.Author_Display_Name AS FirstResponse_By,
          'comment-derived: first non-reporter comment fallback' AS FirstResponse_Source
        FROM UNNEST(c.Comments) AS comment
        WHERE COALESCE(comment.Author_Display_Name, '') != COALESCE(t.Reporter, '')
        ORDER BY comment.Created
        LIMIT 1
      ),
      (
        SELECT AS STRUCT
          comment.Created AS FirstResponse_At,
          comment.Author_Display_Name AS FirstResponse_By,
          'comment-derived: first comment fallback' AS FirstResponse_Source
        FROM UNNEST(c.Comments) AS comment
        ORDER BY comment.Created
        LIMIT 1
      )
    ) AS FirstResponse
  FROM c_all c
  JOIN t ON t.Key = c.Issue_Key
),
ch_all AS (
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
  WHERE REGEXP_CONTAINS(COALESCE(Issue_Key, ''), r'^MSS-')
  GROUP BY Issue_Key
),
ch_resolved_status_metrics AS (
  SELECT
    Issue_Key,
    MIN(Transition_Timestamp) AS ResolvedStatus_At
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog`
  WHERE REGEXP_CONTAINS(COALESCE(Issue_Key, ''), r'^MSS-')
    AND Transitioned_To IN ('Resolved', 'Resolved Customer Tracking')
  GROUP BY Issue_Key
),
ch_waiting_customer AS (
  SELECT
    ch.Issue_Key,
    ch.Transition_Timestamp AS WaitingCustomer_At,
    COALESCE(
      LEAD(ch.Transition_Timestamp) OVER (
        PARTITION BY ch.Issue_Key
        ORDER BY ch.Transition_Timestamp
      ),
      rsm.ResolvedStatus_At,
      t.Resolved,
      t.Updated
    ) AS WaitingCustomer_Until
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
  JOIN t ON t.Key = ch.Issue_Key
  LEFT JOIN ch_resolved_status_metrics rsm ON rsm.Issue_Key = ch.Issue_Key
  WHERE REGEXP_CONTAINS(COALESCE(ch.Issue_Key, ''), r'^MSS-')
    AND ch.Transitioned_To = 'Waiting customer'
),
ch_waiting_customer_metrics AS (
  SELECT
    Issue_Key,
    MIN(WaitingCustomer_At) AS WaitingCustomer_At,
    SUM(
      GREATEST(
        TIMESTAMP_DIFF(WaitingCustomer_Until, WaitingCustomer_At, MINUTE),
        0
      )
    ) AS WaitingCustomer_Minutes
  FROM ch_waiting_customer
  GROUP BY Issue_Key
)

SELECT
  -- Ticket fields
  t.T,
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
  t.Service,
  t.Origin,
  t.SR_Ref,
  t.SyncTime,
  t.TimeToFirstResponse_Elapsed,
  t.TimeToFirstResponse_Elapsed * 60 AS TimeToFirstResponse_Elapsed_Minutes,
  t.TimeToFirstResponse_Elapsed AS TimeToFirstResponse_Elapsed_Hours,
  t.TimeToFirstResponse_Elapsed / 24.0 AS TimeToFirstResponse_Elapsed_Days,
  COALESCE(t.TimeToFirstResponse_Goal, 0.5) AS TimeToFirstResponse_Goal,
  COALESCE(t.TimeToFirstResponse_Goal, 0.5) * 60 AS TimeToFirstResponse_Goal_Minutes,
  COALESCE(t.TimeToFirstResponse_Goal, 0.5) AS TimeToFirstResponse_Goal_Hours,
  COALESCE(t.TimeToFirstResponse_Goal, 0.5) / 24.0 AS TimeToFirstResponse_Goal_Days,
    CASE COALESCE(
      t.TimeToFirstResponse_Breached,
      CASE
        WHEN fr.FirstResponse.FirstResponse_At IS NOT NULL THEN TIMESTAMP_DIFF(fr.FirstResponse.FirstResponse_At, t.Created, MINUTE) > 30
      END
    )
      WHEN TRUE THEN 'Breach'
      WHEN FALSE THEN 'Pass'
    END AS FirstResponseSLA,
  t.TimeToFirstResponse_Cycles,
  t.TimeToResolve_Elapsed,
  t.TimeToResolve_Elapsed * 60 AS TimeToResolve_Elapsed_Minutes,
  t.TimeToResolve_Elapsed AS TimeToResolve_Elapsed_Hours,
  t.TimeToResolve_Elapsed / 24.0 AS TimeToResolve_Elapsed_Days,
  t.TimeToResolve_Goal,
  t.TimeToResolve_Goal * 60 AS TimeToResolve_Goal_Minutes,
  t.TimeToResolve_Goal AS TimeToResolve_Goal_Hours,
  t.TimeToResolve_Goal / 24.0 AS TimeToResolve_Goal_Days,
  t.TimeToResolve_Breached,
  t.TimeToResolve_Cycles,
  t.TimeToResolution_Elapsed,
  t.TimeToResolution_Elapsed * 60 AS TimeToResolution_Elapsed_Minutes,
  t.TimeToResolution_Elapsed AS TimeToResolution_Elapsed_Hours,
  t.TimeToResolution_Elapsed / 24.0 AS TimeToResolution_Elapsed_Days,
  t.TimeToResolution_Goal,
  t.TimeToResolution_Goal * 60 AS TimeToResolution_Goal_Minutes,
  t.TimeToResolution_Goal AS TimeToResolution_Goal_Hours,
  t.TimeToResolution_Goal / 24.0 AS TimeToResolution_Goal_Days,
  t.TimeToResolution_Breached,
  t.TimeToResolution_Cycles,
  t.TimeToApproveNormalChange_Elapsed,
  t.TimeToApproveNormalChange_Elapsed * 60 AS TimeToApproveNormalChange_Elapsed_Minutes,
  t.TimeToApproveNormalChange_Elapsed AS TimeToApproveNormalChange_Elapsed_Hours,
  t.TimeToApproveNormalChange_Elapsed / 24.0 AS TimeToApproveNormalChange_Elapsed_Days,
  t.TimeToApproveNormalChange_Goal,
  t.TimeToApproveNormalChange_Goal * 60 AS TimeToApproveNormalChange_Goal_Minutes,
  t.TimeToApproveNormalChange_Goal AS TimeToApproveNormalChange_Goal_Hours,
  t.TimeToApproveNormalChange_Goal / 24.0 AS TimeToApproveNormalChange_Goal_Days,
  t.TimeToApproveNormalChange_Breached,
  t.TimeToApproveNormalChange_Cycles,
  t.ProlongCase_Elapsed,
  t.ProlongCase_Elapsed * 60 AS ProlongCase_Elapsed_Minutes,
  t.ProlongCase_Elapsed AS ProlongCase_Elapsed_Hours,
  t.ProlongCase_Elapsed / 24.0 AS ProlongCase_Elapsed_Days,
  t.ProlongCase_Goal,
  t.ProlongCase_Goal * 60 AS ProlongCase_Goal_Minutes,
  t.ProlongCase_Goal AS ProlongCase_Goal_Hours,
  t.ProlongCase_Goal / 24.0 AS ProlongCase_Goal_Days,
  t.ProlongCase_Breached,
  t.ProlongCase_Cycles,
  t.TimeToCloseAfterResolution_Elapsed,
  t.TimeToCloseAfterResolution_Elapsed * 60 AS TimeToCloseAfterResolution_Elapsed_Minutes,
  t.TimeToCloseAfterResolution_Elapsed AS TimeToCloseAfterResolution_Elapsed_Hours,
  t.TimeToCloseAfterResolution_Elapsed / 24.0 AS TimeToCloseAfterResolution_Elapsed_Days,
  t.TimeToCloseAfterResolution_Goal,
  t.TimeToCloseAfterResolution_Goal * 60 AS TimeToCloseAfterResolution_Goal_Minutes,
  t.TimeToCloseAfterResolution_Goal AS TimeToCloseAfterResolution_Goal_Hours,
  t.TimeToCloseAfterResolution_Goal / 24.0 AS TimeToCloseAfterResolution_Goal_Days,
  t.TimeToCloseAfterResolution_Breached,
  t.TimeToCloseAfterResolution_Cycles,
  t.AppSupEscalation,

  -- Comment aggregates
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
  fr.FirstResponse.FirstResponse_At AS FirstResponse_At,
  fr.FirstResponse.FirstResponse_By AS FirstResponse_By,
  TIMESTAMP_DIFF(fr.FirstResponse.FirstResponse_At, t.Created, MINUTE) AS FirstResponse_Minutes,
  TIMESTAMP_DIFF(fr.FirstResponse.FirstResponse_At, t.Created, MINUTE) / 60.0 AS FirstResponse_Hours,
  TIMESTAMP_DIFF(fr.FirstResponse.FirstResponse_At, t.Created, MINUTE) / 1440.0 AS FirstResponse_Days,
  fr.FirstResponse.FirstResponse_Source AS FirstResponse_Source,
  wcm.WaitingCustomer_At,
  wcm.WaitingCustomer_Minutes,
  wcm.WaitingCustomer_Minutes / 60.0 AS WaitingCustomer_Hours,
  wcm.WaitingCustomer_Minutes / 1440.0 AS WaitingCustomer_Days,
  rsm.ResolvedStatus_At,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE)
  END AS CreatedToResolved_Minutes,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE) / 60.0
  END AS CreatedToResolved_Hours,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE) / 1440.0
  END AS CreatedToResolved_Days,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE) - COALESCE(wcm.WaitingCustomer_Minutes, 0)
  END AS NetResolutionTime_Minutes,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN (TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE) - COALESCE(wcm.WaitingCustomer_Minutes, 0)) / 60.0
  END AS NetResolutionTime_Hours,
  CASE
    WHEN COALESCE(rsm.ResolvedStatus_At, t.Resolved) IS NOT NULL THEN (TIMESTAMP_DIFF(COALESCE(rsm.ResolvedStatus_At, t.Resolved), t.Created, MINUTE) - COALESCE(wcm.WaitingCustomer_Minutes, 0)) / 1440.0
  END AS NetResolutionTime_Days,
  c.Comments,

  -- Changelog aggregates
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
FROM t
LEFT JOIN c_all c ON c.Issue_Key = t.Key
LEFT JOIN c_first fr ON fr.Issue_Key = t.Key
LEFT JOIN ch_all ch ON ch.Issue_Key = t.Key
LEFT JOIN ch_resolved_status_metrics rsm ON rsm.Issue_Key = t.Key
LEFT JOIN ch_waiting_customer_metrics wcm ON wcm.Issue_Key = t.Key