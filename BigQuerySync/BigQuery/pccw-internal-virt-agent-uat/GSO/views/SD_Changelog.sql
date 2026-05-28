WITH sd_data AS (
  SELECT *
  FROM `pccw-internal-virt-agent-uat.GSO.Jira`
  WHERE Ticket_Key LIKE 'GSDT%'
     OR Ticket_Key LIKE 'CCPROV%'
),
ordered AS (
  SELECT
    cl.Issue_Key,
    cl.History_ID AS Changelog_ID,
    cl.Transition_Timestamp,
    cl.Transitioned_From,
    cl.Transitioned_To,
    cl.Transitioned_By_Account_ID,
    cl.Transitioned_By_Display_Name AS Transitioned_By,
    LAG(cl.Transition_Timestamp) OVER (
      PARTITION BY cl.Issue_Key
      ORDER BY cl.Transition_Timestamp
    ) AS Original_Previous_Transition_Timestamp,
    LEAD(cl.Transition_Timestamp) OVER (
      PARTITION BY cl.Issue_Key
      ORDER BY cl.Transition_Timestamp
    ) AS next_transition,
    ROW_NUMBER() OVER (
      PARTITION BY cl.Issue_Key
      ORDER BY cl.Transition_Timestamp
    ) AS row_num,
    sd_data.Created,
    sd_data.Resolved,
    sd_data.Status AS current_status
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` cl
  LEFT JOIN sd_data
    ON cl.Issue_Key = sd_data.Ticket_Key
  WHERE cl.Issue_Key LIKE 'GSDT%'
     OR cl.Issue_Key LIKE 'CCPROV%'
),
entered_status AS (
  SELECT
    Issue_Key,
    Transitioned_To AS status_label,
    Transition_Timestamp AS status_start,
    COALESCE(next_transition, Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM ordered
  WHERE Transitioned_To IS NOT NULL
),
initial_status AS (
  SELECT
    Issue_Key,
    COALESCE(Transitioned_From, current_status, 'Created (unknown)') AS status_label,
    Created AS status_start,
    Transition_Timestamp AS status_end
  FROM ordered
  WHERE row_num = 1
    AND Transition_Timestamp IS NOT NULL
),
no_changelog AS (
  SELECT
    sd.Ticket_Key,
    sd.Status AS status_label,
    sd.Created AS status_start,
    COALESCE(sd.Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM sd_data sd
  WHERE NOT EXISTS (
    SELECT 1 FROM ordered o WHERE o.Issue_Key = sd.Ticket_Key
  )
),
durations AS (
  SELECT * FROM entered_status
  UNION ALL
  SELECT * FROM initial_status
  UNION ALL
  SELECT * FROM no_changelog
),
filtered_durations AS (
  SELECT *
  FROM durations
  WHERE status_start IS NOT NULL
    AND status_end IS NOT NULL
    AND status_start < status_end
),
status_transitions AS (
  SELECT
    Issue_Key,
    MIN(CASE WHEN Transitioned_To = 'In Progress' THEN Transition_Timestamp END) AS In_Progress_Timestamp,
    MIN(CASE WHEN Transitioned_To = 'Ready to Deploy' THEN Transition_Timestamp END) AS Ready_To_Deploy_Timestamp
  FROM ordered
  GROUP BY Issue_Key
)

SELECT
  sd.Ticket_Key,
  ord.Changelog_ID,
  ord.Transition_Timestamp,
  ord.Transitioned_From,
  ord.Transitioned_To,
  ord.Transitioned_By_Account_ID,
  ord.Transitioned_By,
  ord.Original_Previous_Transition_Timestamp,

  sd.T,
  sd.Summary,
  sd.Status,
  sd.Assignee,
  sd.Created,
  sd.Updated,
  sd.Resolved,
  sd.LinkedProject_Clean,
  sd.AppSupEscalation,
  sd.Resolution,
  sd.SyncTime AS sd_SyncTime,
  filtered_durations.status_label,
  filtered_durations.status_start,
  filtered_durations.status_end,
  TIMESTAMP_DIFF(filtered_durations.status_end, filtered_durations.status_start, MINUTE) AS status_duration_minutes,

  CASE
    WHEN ord.Original_Previous_Transition_Timestamp IS NULL THEN sd.Created
    ELSE ord.Original_Previous_Transition_Timestamp
  END AS Final_Previous_Transition_Timestamp,

  ord.Transitioned_From AS Transitioned_From_Sorted,
  ord.Transitioned_To AS Transitioned_To_Sorted,

  status_transitions.In_Progress_Timestamp,
  status_transitions.Ready_To_Deploy_Timestamp,
  DATETIME_DIFF(status_transitions.Ready_To_Deploy_Timestamp, status_transitions.In_Progress_Timestamp, DAY) AS Days_In_Progress_To_Deploy

FROM sd_data sd
LEFT JOIN filtered_durations
  ON filtered_durations.Issue_Key = sd.Ticket_Key
LEFT JOIN ordered ord
  ON ord.Issue_Key = filtered_durations.Issue_Key
 AND ord.Transition_Timestamp = filtered_durations.status_start
LEFT JOIN status_transitions
  ON status_transitions.Issue_Key = sd.Ticket_Key

ORDER BY sd.Ticket_Key, filtered_durations.status_start
