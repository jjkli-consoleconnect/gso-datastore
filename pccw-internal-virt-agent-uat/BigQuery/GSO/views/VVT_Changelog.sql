WITH vvt_tickets AS (
  SELECT
    t.T AS IssueType,
    t.Project,
    t.Key AS Ticket_Key,
    t.Summary,
    t.Status,
    t.Priority,
    t.Resolution,
    t.Created,
    t.Updated,
    t.Resolved,
    t.Reporter,
    t.Assignee AS Current_Assignee,
    t.Component,
    t.AssociatedTeam,
    CASE 
      WHEN t.AssociatedTeam = 'Direct Cost Team' THEN 'Direct Cost Team'
      WHEN t.AssociatedTeam = 'Network Team' THEN 'Network Team'
      ELSE 'Others'
    END AS CostType,
    t.TransactionStatus,
    t.SyncTime,
    COALESCE(t.IsDeleted, FALSE) AS IsDeleted,
    t.DeletedAt
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
  WHERE COALESCE(t.Project, '') = 'Vendor Verification Team'
     OR REGEXP_CONTAINS(COALESCE(t.Key, ''), r'^VVT-')
),
status_history AS (
  SELECT
    ch.Issue_Key AS Ticket_Key,
    ch.History_ID AS Status_Changelog_ID,
    ch.Transition_Timestamp AS Status_Transition_Timestamp,
    ch.Transitioned_From AS Previous_Status,
    ch.Transitioned_To AS Status_Label,
    ch.Transitioned_By_Account_ID AS Status_Changed_By_Account_ID,
    ch.Transitioned_By_Display_Name AS Status_Changed_By,
    LEAD(ch.Transition_Timestamp) OVER (
      PARTITION BY ch.Issue_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID, COALESCE(ch.Change_Item_Index, 0)
    ) AS Next_Status_Change_Timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY ch.Issue_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID, COALESCE(ch.Change_Item_Index, 0)
    ) AS Status_Row_Num
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
  WHERE REGEXP_CONTAINS(COALESCE(ch.Issue_Key, ''), r'^VVT-')
    AND NOT COALESCE(ch.IsDeleted, FALSE)
    AND LOWER(COALESCE(ch.Changed_Field, 'status')) = 'status'
),
entered_status AS (
  SELECT
    sh.Ticket_Key,
    sh.Status_Changelog_ID,
    sh.Status_Transition_Timestamp,
    sh.Previous_Status,
    sh.Status_Label,
    sh.Status_Changed_By_Account_ID,
    sh.Status_Changed_By,
    sh.Status_Transition_Timestamp AS Status_Start,
    COALESCE(sh.Next_Status_Change_Timestamp, v.Resolved, CURRENT_TIMESTAMP()) AS Status_End
  FROM status_history sh
  JOIN vvt_tickets v
    ON v.Ticket_Key = sh.Ticket_Key
  WHERE sh.Status_Label IS NOT NULL
    AND sh.Status_Transition_Timestamp IS NOT NULL
),
initial_status AS (
  SELECT
    v.Ticket_Key,
    CAST(NULL AS STRING) AS Status_Changelog_ID,
    fh.Status_Transition_Timestamp,
    CAST(NULL AS STRING) AS Previous_Status,
    COALESCE(fh.Previous_Status, v.Status, 'Created (unknown)') AS Status_Label,
    CAST(NULL AS STRING) AS Status_Changed_By_Account_ID,
    CAST(NULL AS STRING) AS Status_Changed_By,
    v.Created AS Status_Start,
    fh.Status_Transition_Timestamp AS Status_End
  FROM vvt_tickets v
  JOIN (
    SELECT *
    FROM status_history
    WHERE Status_Row_Num = 1
  ) fh
    ON fh.Ticket_Key = v.Ticket_Key
  WHERE v.Created IS NOT NULL
    AND fh.Status_Transition_Timestamp IS NOT NULL
),
tickets_without_status_changelog AS (
  SELECT
    v.Ticket_Key,
    CAST(NULL AS STRING) AS Status_Changelog_ID,
    CAST(NULL AS TIMESTAMP) AS Status_Transition_Timestamp,
    CAST(NULL AS STRING) AS Previous_Status,
    v.Status AS Status_Label,
    CAST(NULL AS STRING) AS Status_Changed_By_Account_ID,
    CAST(NULL AS STRING) AS Status_Changed_By,
    v.Created AS Status_Start,
    COALESCE(v.Resolved, CURRENT_TIMESTAMP()) AS Status_End
  FROM vvt_tickets v
  WHERE NOT EXISTS (
    SELECT 1
    FROM status_history sh
    WHERE sh.Ticket_Key = v.Ticket_Key
  )
),
status_intervals AS (
  SELECT * FROM entered_status
  UNION ALL
  SELECT * FROM initial_status
  UNION ALL
  SELECT * FROM tickets_without_status_changelog
),
filtered_status_intervals AS (
  SELECT
    Ticket_Key,
    Status_Changelog_ID,
    Status_Transition_Timestamp,
    Previous_Status,
    Status_Label,
    Status_Changed_By_Account_ID,
    Status_Changed_By,
    Status_Start,
    Status_End,
    TIMESTAMP_DIFF(Status_End, Status_Start, SECOND) AS Status_Duration_Seconds,
    ROUND(TIMESTAMP_DIFF(Status_End, Status_Start, SECOND) / 60.0, 2) AS Status_Duration_Minutes,
    ROUND(TIMESTAMP_DIFF(Status_End, Status_Start, SECOND) / 3600.0, 2) AS Status_Duration_Hours,
    ROUND(TIMESTAMP_DIFF(Status_End, Status_Start, SECOND) / 86400.0, 2) AS Status_Duration_Days
  FROM status_intervals
  WHERE Status_Start IS NOT NULL
    AND Status_End IS NOT NULL
    AND Status_Start < Status_End
),
assignee_history AS (
  SELECT
    ch.Issue_Key AS Ticket_Key,
    ch.History_ID AS Assignee_Changelog_ID,
    ch.Transition_Timestamp AS Assignee_Transition_Timestamp,
    NULLIF(ch.From_Value, '') AS From_Assignee,
    NULLIF(ch.To_Value, '') AS To_Assignee,
    ch.From_ID AS From_Assignee_Account_ID,
    ch.To_ID AS To_Assignee_Account_ID,
    LEAD(ch.Transition_Timestamp) OVER (
      PARTITION BY ch.Issue_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID, COALESCE(ch.Change_Item_Index, 0)
    ) AS Next_Assignee_Change_Timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY ch.Issue_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID, COALESCE(ch.Change_Item_Index, 0)
    ) AS Assignee_Row_Num
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
  WHERE REGEXP_CONTAINS(COALESCE(ch.Issue_Key, ''), r'^VVT-')
    AND NOT COALESCE(ch.IsDeleted, FALSE)
    AND LOWER(COALESCE(ch.Changed_Field, '')) = 'assignee'
),
entered_assignee AS (
  SELECT
    ah.Ticket_Key,
    COALESCE(ah.To_Assignee, 'Unassigned') AS Assignee_At_Time,
    ah.To_Assignee_Account_ID AS Assignee_Account_ID,
    ah.Assignee_Transition_Timestamp AS Assignee_Start,
    COALESCE(ah.Next_Assignee_Change_Timestamp, v.Resolved, CURRENT_TIMESTAMP()) AS Assignee_End,
    'assignee_changelog' AS Assignee_Source
  FROM assignee_history ah
  JOIN vvt_tickets v
    ON v.Ticket_Key = ah.Ticket_Key
),
initial_assignee AS (
  SELECT
    v.Ticket_Key,
    COALESCE(ah.From_Assignee, 'Unassigned') AS Assignee_At_Time,
    ah.From_Assignee_Account_ID AS Assignee_Account_ID,
    v.Created AS Assignee_Start,
    ah.Assignee_Transition_Timestamp AS Assignee_End,
    'assignee_changelog' AS Assignee_Source
  FROM vvt_tickets v
  JOIN (
    SELECT *
    FROM assignee_history
    WHERE Assignee_Row_Num = 1
  ) ah
    ON ah.Ticket_Key = v.Ticket_Key
  WHERE v.Created IS NOT NULL
    AND ah.Assignee_Transition_Timestamp IS NOT NULL
),
tickets_without_assignee_history AS (
  SELECT
    v.Ticket_Key,
    COALESCE(v.Current_Assignee, 'Unassigned') AS Assignee_At_Time,
    CAST(NULL AS STRING) AS Assignee_Account_ID,
    v.Created AS Assignee_Start,
    COALESCE(v.Resolved, CURRENT_TIMESTAMP()) AS Assignee_End,
    'ticket_snapshot_fallback' AS Assignee_Source
  FROM vvt_tickets v
  WHERE NOT EXISTS (
    SELECT 1
    FROM assignee_history ah
    WHERE ah.Ticket_Key = v.Ticket_Key
  )
),
assignee_intervals AS (
  SELECT * FROM entered_assignee
  UNION ALL
  SELECT * FROM initial_assignee
  UNION ALL
  SELECT * FROM tickets_without_assignee_history
),
status_assignee_intervals AS (
  SELECT
    s.Ticket_Key,
    s.Status_Changelog_ID,
    s.Status_Transition_Timestamp,
    s.Previous_Status,
    s.Status_Label,
    s.Status_Changed_By_Account_ID,
    s.Status_Changed_By,
    s.Status_Start,
    s.Status_End,
    s.Status_Duration_Seconds,
    s.Status_Duration_Minutes,
    s.Status_Duration_Hours,
    s.Status_Duration_Days,
    a.Assignee_At_Time,
    a.Assignee_Account_ID,
    a.Assignee_Source,
    a.Assignee_Start,
    a.Assignee_End,
    GREATEST(s.Status_Start, a.Assignee_Start) AS Interval_Start,
    LEAST(s.Status_End, a.Assignee_End) AS Interval_End
  FROM filtered_status_intervals s
  JOIN assignee_intervals a
    ON a.Ticket_Key = s.Ticket_Key
   AND s.Status_Start < a.Assignee_End
   AND a.Assignee_Start < s.Status_End
),
final_intervals AS (
  SELECT
    *,
    TIMESTAMP_DIFF(Interval_End, Interval_Start, SECOND) AS Assignee_Status_Duration_Seconds,
    ROUND(TIMESTAMP_DIFF(Interval_End, Interval_Start, SECOND) / 60.0, 2) AS Assignee_Status_Duration_Minutes,
    ROUND(TIMESTAMP_DIFF(Interval_End, Interval_Start, SECOND) / 3600.0, 2) AS Assignee_Status_Duration_Hours,
    ROUND(TIMESTAMP_DIFF(Interval_End, Interval_Start, SECOND) / 86400.0, 2) AS Assignee_Status_Duration_Days
  FROM status_assignee_intervals
  WHERE Interval_Start IS NOT NULL
    AND Interval_End IS NOT NULL
    AND Interval_Start < Interval_End
)
SELECT
  v.Ticket_Key AS Issue_Key,
  f.Status_Changelog_ID AS Changelog_ID,
  f.Status_Transition_Timestamp AS Transition_Timestamp,
  f.Previous_Status AS Transitioned_From,
  f.Status_Label AS Transitioned_To,
  f.Status_Changed_By_Account_ID AS Transitioned_By_Account_ID,
  f.Status_Changed_By AS Transitioned_By,

  v.IssueType,
  v.Project,
  v.Summary,
  v.Status AS Current_Status,
  v.Priority,
  v.Resolution,
  v.Created AS Ticket_Created,
  v.Updated AS Ticket_Updated,
  v.Resolved AS Ticket_Resolved,
  v.Reporter,
  v.Current_Assignee AS Assignee,
  v.Component,
  v.AssociatedTeam,
  v.CostType,
  v.TransactionStatus,
  v.SyncTime,
  v.IsDeleted,
  v.DeletedAt,

  f.Status_Label AS status_label,
  f.Status_Start AS status_start,
  f.Status_End AS status_end,
  f.Status_Duration_Seconds AS status_duration_seconds,
  f.Status_Duration_Minutes AS status_duration_minutes,
  f.Status_Duration_Hours AS status_duration_hours,
  f.Status_Duration_Days AS status_duration_days,

  f.Assignee_At_Time,
  f.Assignee_Account_ID,
  f.Assignee_Source,
  f.Assignee_Start,
  f.Assignee_End,
  f.Interval_Start,
  f.Interval_End,
  f.Assignee_Status_Duration_Seconds,
  f.Assignee_Status_Duration_Minutes,
  f.Assignee_Status_Duration_Hours,
  f.Assignee_Status_Duration_Days
FROM final_intervals f
JOIN vvt_tickets v
  ON v.Ticket_Key = f.Ticket_Key
ORDER BY v.Ticket_Key, f.Interval_Start, f.Status_Label, f.Assignee_At_Time
