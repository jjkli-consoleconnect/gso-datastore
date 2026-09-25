-- Jira combined snapshot optimized for Looker Studio and ticket-centric analytics.
-- Grain: 1 row per ticket (no fan-out). Comments and Changelog are pre-aggregated 1:1 per ticket
-- and provided as: (a) convenient summary columns (counts, latest) and (b) full arrays of structs.

WITH t AS (
  SELECT
    T,
    Project,
    Key,
    Summary,
    RFODescription,
    RFOCategory,
    Fix,
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
  WHERE IsDeleted IS FALSE OR IsDeleted IS NULL
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
  GROUP BY Issue_Key
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
  GROUP BY Issue_Key
)

SELECT
  -- Ticket fields
  t.T,
  t.Project,
  t.Key,
  t.Summary,
  t.RFODescription,
  t.RFOCategory,
  t.Fix,
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
LEFT JOIN ch_all ch ON ch.Issue_Key = t.Key
