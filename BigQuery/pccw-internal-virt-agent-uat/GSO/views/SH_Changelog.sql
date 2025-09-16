WITH OrderedChangeLog AS (
  SELECT
    changelog.Issue_Key,
    changelog.History_ID AS Changelog_ID,
    changelog.Transition_Timestamp,
    changelog.Transitioned_From,
    changelog.Transitioned_To,
    changelog.Transitioned_By_Account_ID,
    changelog.Transitioned_By_Display_Name AS Transitioned_By,
    LAG(changelog.Transition_Timestamp) OVER (
      PARTITION BY changelog.Issue_Key
      ORDER BY changelog.History_ID ASC
    ) AS Original_Previous_Transition_Timestamp
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraChangelog` changelog
  WHERE
    changelog.Issue_Key LIKE 'SH%'
)

SELECT
  -- From OrderedChangeLog
  OrderedChangeLog.Issue_Key,
  OrderedChangeLog.Changelog_ID,
  OrderedChangeLog.Transition_Timestamp,
  OrderedChangeLog.Transitioned_From,
  OrderedChangeLog.Transitioned_To,
  OrderedChangeLog.Transitioned_By_Account_ID,
  OrderedChangeLog.Transitioned_By,
  OrderedChangeLog.Original_Previous_Transition_Timestamp,

  -- From SH (aliased to avoid duplication)
  SH.Type,
  SH.Summary,
  SH.Status,
  SH.Priority,
  SH.Assignee,
  SH.Ticket_Created,
  SH.Ticket_Updated,
  SH.Ticket_Resolved,
  SH.linkedkeys,
  SH.AppSupEscalation,
  SH.Resolution,
  SH.SyncTime AS SH_SyncTime,
  SH.StoryPoints,
  SH.Resolution_hrs,
  SH.Resolution_days,
  SH.SLA_Resolution_Target_hrs,
  SH.SLA_Resolution_Status,
  SH.CCASSolved,
  SH.CCSUPSolved,
  SH.SLSUPSolved,
  SH.CCONBSolved,
  SH.COPSSolved,
  SH.CSCMSolved,
  SH.TACSolved,
  SH.CCT4Solved,
  SH.SHSolved,
  SH.AS3491Solved,
  SH.TCMSolved,
  SH.Comment_ID,
  SH.Comment_Author,
  SH.Comment_Created,
  SH.Comment_Updated,
  SH.Comment_Body,
  SH.Visibility_Type,
  SH.Visibility_Value,
  SH.Comment_Shift,

  -- Derived fields
  CASE
    WHEN OrderedChangeLog.Original_Previous_Transition_Timestamp IS NULL THEN SH.Ticket_Created
    ELSE OrderedChangeLog.Original_Previous_Transition_Timestamp
  END AS Final_Previous_Transition_Timestamp,

  OrderedChangeLog.Transitioned_From AS Transitioned_From_Sorted,
  OrderedChangeLog.Transitioned_To AS Transitioned_To_Sorted

FROM
  OrderedChangeLog
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.SH` SH
ON
  OrderedChangeLog.Issue_Key = SH.Issue_Key

ORDER BY
  OrderedChangeLog.Transition_Timestamp DESC
