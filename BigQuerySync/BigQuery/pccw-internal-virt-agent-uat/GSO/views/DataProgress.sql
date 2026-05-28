SELECT
  'JiraComments' AS Source,
  Project,
  WindowStart,
  WindowEnd,
  Status,
  LastRun,
  RowCount
FROM
  `pccw-internal-virt-agent-uat.GSO.JiraComments_progress`

UNION ALL

SELECT
  'JiraChangelog' AS Source,
  Project,
  WindowStart,
  WindowEnd,
  Status,
  LastRun,
  RowCount
FROM
  `pccw-internal-virt-agent-uat.GSO.JiraChangelog_progress`

UNION ALL

SELECT
  'JiraTickets' AS Source,
  Project,
  WindowStart,
  WindowEnd,
  Status,
  LastRun,
  RowCount
FROM
  `pccw-internal-virt-agent-uat.GSO.JiraTickets_progress`
