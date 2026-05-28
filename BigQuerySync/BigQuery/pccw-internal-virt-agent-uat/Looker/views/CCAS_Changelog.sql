WITH OrderedChangeLog AS (
  SELECT
    changelog.Issue_Key,
    changelog.History_ID,
    changelog.Transition_Timestamp,
    changelog.Transitioned_From,
    changelog.Transitioned_To,
    changelog.Transitioned_By_Account_ID,
    changelog.Transitioned_By_Display_Name AS Transitioned_By,
    COALESCE(userid.Title, 'No Title Provided') AS Title,
    COALESCE(userid.Team, 'No Team Provided') AS Team,
    LAG(changelog.Transition_Timestamp) OVER (
      PARTITION BY changelog.Issue_Key
      ORDER BY changelog.History_ID ASC
    ) AS Original_Previous_Transition_Timestamp
  FROM
    `pccw-internal-virt-agent-uat.JIRAProjects.CCAS_changelog` changelog
    LEFT JOIN
    `pccw-internal-virt-agent-uat.RemedyICS.UserID` userid
  ON
    changelog.Transitioned_By_Display_Name = userid.JiraID
)
SELECT
  OrderedChangeLog.*,
  ccas.*,
  CASE
    WHEN OrderedChangeLog.Original_Previous_Transition_Timestamp IS NULL THEN ccas.Created
    ELSE OrderedChangeLog.Original_Previous_Transition_Timestamp
  END AS Final_Previous_Transition_Timestamp,
  OrderedChangeLog.Transitioned_From AS Transitioned_From_Sorted,
  OrderedChangeLog.Transitioned_To AS Transitioned_To_Sorted

FROM
  OrderedChangeLog
LEFT JOIN
  `pccw-internal-virt-agent-uat.Looker.CCAS` ccas
ON
  OrderedChangeLog.Issue_Key = ccas.Key

ORDER BY
  OrderedChangeLog.Transition_Timestamp DESC
