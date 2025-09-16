WITH OrderedChangeLog AS (
  SELECT
    changelog.Issue_Key,
    changelog.History_ID,
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
    WHERE changelog.Issue_Key LIKE 'CSM%'

)
SELECT
  OrderedChangeLog.*,
  csm.*,
  CASE
    WHEN OrderedChangeLog.Original_Previous_Transition_Timestamp IS NULL THEN csm.Created
    ELSE OrderedChangeLog.Original_Previous_Transition_Timestamp
  END AS Final_Previous_Transition_Timestamp,
  OrderedChangeLog.Transitioned_From AS Transitioned_From_Sorted,
  OrderedChangeLog.Transitioned_To AS Transitioned_To_Sorted

FROM
  OrderedChangeLog
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.CSM` csm
ON
  OrderedChangeLog.Issue_Key = csm.Ticket_Key

ORDER BY
  OrderedChangeLog.Transition_Timestamp DESC
