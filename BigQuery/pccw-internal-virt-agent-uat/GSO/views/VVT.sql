yes aWITH vvt_tickets AS (
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
    t.Assignee,
    t.Component,
    ARRAY_TO_STRING(t.Component, ', ') AS Component_Joined,
    t.Links,
    t.AssociatedTeam,
    CASE 
      WHEN t.AssociatedTeam = 'Direct Cost Team' THEN 'Direct Cost'
      WHEN t.AssociatedTeam = 'Network Team' THEN 'Network'
      ELSE 'Others'
    END AS CostType,
      CASE
        WHEN t.TransactionStatus = 'Awaiting for Marking receipt' THEN 'Mark Receipt'
        WHEN t.TransactionStatus = 'Awaiting for PO - Amount Variance' THEN 'Amount Variance'
        WHEN t.TransactionStatus = 'Awaiting for Credit note' THEN 'Credit Note'
        WHEN t.TransactionStatus = 'Awaiting for PO - Replacement PO' THEN 'Replacement PO'
        WHEN t.TransactionStatus = 'Dispute reason' THEN 'Dispute Reason'
        WHEN t.TransactionStatus = 'Awaiting for PO - Date Variance' THEN 'Date Variance'
        WHEN t.TransactionStatus = 'Awaiting for PO - New PO' THEN 'New PO'
        ELSE t.TransactionStatus
      END AS TransactionStatus,
    t.SyncTime,
    COALESCE(t.IsDeleted, FALSE) AS IsDeleted,
    t.DeletedAt,

    -- Helpful visualisation fields
    CASE
      WHEN t.Resolved IS NULL THEN 'Open'
      ELSE 'Closed'
    END AS TicketState,
    DATE(t.Created) AS CreatedDate,
    DATE(t.Updated) AS UpdatedDate,
    DATE(t.Resolved) AS ResolvedDate,
    EXTRACT(YEAR FROM t.Created) AS CreatedYear,
    FORMAT_DATE('%Y-%m', DATE(t.Created)) AS CreatedMonth,
    TIMESTAMP_DIFF(COALESCE(t.Resolved, CURRENT_TIMESTAMP()), t.Created, DAY) AS TicketAge_Days,
    TIMESTAMP_DIFF(t.Resolved, t.Created, HOUR) AS LeadTime_Hours,
    TIMESTAMP_DIFF(t.Resolved, t.Created, DAY) AS LeadTime_Days,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t.Updated, DAY) AS DaysSinceLastUpdate


  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
  WHERE COALESCE(t.Project, '') = 'Vendor Verification Team'
     OR REGEXP_CONTAINS(COALESCE(t.Key, ''), r'^VVT-')
),
comments_agg AS (
  SELECT
    c.Issue_Key,
    COUNT(*) AS Comment_Count,
    MAX(c.Created) AS Last_Comment_At,
    STRING_AGG(DISTINCT c.Author_Display_Name, ', ' ORDER BY c.Author_Display_Name) AS Comment_Authors,
    ARRAY_AGG(
      STRUCT(
        c.Comment_ID,
        c.Author_Account_ID,
        c.Author_Display_Name,
        c.Created,
        c.Updated,
        c.Body,
        c.Visibility_Type,
        c.Visibility_Value,
        c.SyncTime,
        c.InsertedAt
      )
      ORDER BY c.Created DESC
    ) AS Comments,
    ARRAY_AGG(
      STRUCT(
        c.Comment_ID,
        c.Author_Account_ID,
        c.Author_Display_Name,
        c.Created,
        c.Updated,
        c.Body,
        c.Visibility_Type,
        c.Visibility_Value,
        c.SyncTime,
        c.InsertedAt
      )
      ORDER BY c.Created DESC
      LIMIT 1
    )[OFFSET(0)] AS Last_Comment
  FROM `pccw-internal-virt-agent-uat.GSO.JiraComments` c
  WHERE REGEXP_CONTAINS(COALESCE(c.Issue_Key, ''), r'^VVT-')
  GROUP BY c.Issue_Key
),
ordered_status_changes AS (
  SELECT
    v.Ticket_Key,
    ch.History_ID,
    ch.Transition_Timestamp,
    ch.Transitioned_From,
    ch.Transitioned_To,
    ch.Transitioned_By_Account_ID,
    ch.Transitioned_By_Display_Name,
    v.Created AS Ticket_Created,
    v.Resolved AS Ticket_Resolved,
    v.Status AS Current_Status,
    LEAD(ch.Transition_Timestamp) OVER (
      PARTITION BY v.Ticket_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID
    ) AS Next_Transition_Timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY v.Ticket_Key
      ORDER BY ch.Transition_Timestamp, ch.History_ID
    ) AS Row_Num
  FROM vvt_tickets v
  LEFT JOIN `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
    ON ch.Issue_Key = v.Ticket_Key
   AND NOT COALESCE(ch.IsDeleted, FALSE)
   AND LOWER(COALESCE(ch.Changed_Field, 'status')) = 'status'
),
entered_status AS (
  SELECT
    Ticket_Key,
    Transitioned_To AS status_label,
    Transition_Timestamp AS status_start,
    COALESCE(Next_Transition_Timestamp, Ticket_Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM ordered_status_changes
  WHERE Transitioned_To IS NOT NULL
    AND Transition_Timestamp IS NOT NULL
),
initial_status AS (
  SELECT
    Ticket_Key,
    COALESCE(Transitioned_From, Current_Status, 'Created (unknown)') AS status_label,
    Ticket_Created AS status_start,
    Transition_Timestamp AS status_end
  FROM ordered_status_changes
  WHERE Row_Num = 1
    AND Transition_Timestamp IS NOT NULL
),
tickets_without_changelog AS (
  SELECT
    v.Ticket_Key,
    v.Status AS status_label,
    v.Created AS status_start,
    COALESCE(v.Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM vvt_tickets v
  WHERE NOT EXISTS (
    SELECT 1
    FROM ordered_status_changes osc
    WHERE osc.Ticket_Key = v.Ticket_Key
      AND osc.Transition_Timestamp IS NOT NULL
  )
),
status_duration_rows AS (
  SELECT
    Ticket_Key,
    status_label,
    status_start,
    status_end,
    TIMESTAMP_DIFF(status_end, status_start, SECOND) AS status_duration_seconds,
    ROUND(TIMESTAMP_DIFF(status_end, status_start, SECOND) / 60.0, 2) AS status_duration_minutes,
    ROUND(TIMESTAMP_DIFF(status_end, status_start, SECOND) / 3600.0, 2) AS status_duration_hours,
    ROUND(TIMESTAMP_DIFF(status_end, status_start, SECOND) / 86400.0, 2) AS status_duration_days
  FROM (
    SELECT * FROM entered_status
    UNION ALL
    SELECT * FROM initial_status
    UNION ALL
    SELECT * FROM tickets_without_changelog
  )
  WHERE status_start IS NOT NULL
    AND status_end IS NOT NULL
    AND status_start < status_end
),
status_duration_agg AS (
  SELECT
    Ticket_Key,
    COUNT(*) AS Status_Interval_Count,
    SUM(status_duration_seconds) AS Total_Status_Duration_Seconds,
    ROUND(SUM(status_duration_seconds) / 60.0, 2) AS Total_Status_Duration_Minutes,
    ROUND(SUM(status_duration_seconds) / 3600.0, 2) AS Total_Status_Duration_Hours,
    ROUND(SUM(status_duration_seconds) / 86400.0, 2) AS Total_Status_Duration_Days,
    SUM(CASE WHEN LOWER(TRIM(status_label)) = 'backlog' THEN status_duration_seconds END) AS Seconds_Backlog,
    SUM(CASE WHEN LOWER(TRIM(status_label)) = 'in progress' THEN status_duration_seconds END) AS Seconds_In_Progress,
    SUM(CASE WHEN LOWER(TRIM(status_label)) = 'waiting for feedback' THEN status_duration_seconds END) AS Seconds_Waiting_For_Feedback,
    SUM(CASE WHEN LOWER(TRIM(status_label)) IN ('acceptance', 'accepted') THEN status_duration_seconds END) AS Seconds_Acceptance,
    SUM(CASE WHEN LOWER(TRIM(status_label)) = 'rejected' THEN status_duration_seconds END) AS Seconds_Rejected,
    SUM(CASE WHEN LOWER(TRIM(status_label)) = 'pending' THEN status_duration_seconds END) AS Seconds_Pending,
    GREATEST(
      SUM(status_duration_seconds) - COALESCE(SUM(CASE WHEN LOWER(TRIM(status_label)) = 'waiting for feedback' THEN status_duration_seconds END), 0),
      0
    ) AS Active_Verification_Time_Seconds,
    ARRAY_AGG(
      STRUCT(
        status_label AS Status,
        status_start AS StartedAt,
        status_end AS EndedAt,
        status_duration_seconds AS Duration_Seconds,
        status_duration_minutes AS Duration_Minutes,
        status_duration_hours AS Duration_Hours,
        status_duration_days AS Duration_Days
      )
      ORDER BY status_start
    ) AS Status_Durations
  FROM status_duration_rows
  GROUP BY Ticket_Key
),
status_summary_by_status AS (
  SELECT
    Ticket_Key,
    status_label,
    COUNT(*) AS Status_Entry_Count,
    SUM(status_duration_seconds) AS Total_Seconds,
    ROUND(SUM(status_duration_seconds) / 60.0, 2) AS Total_Minutes,
    ROUND(SUM(status_duration_seconds) / 3600.0, 2) AS Total_Hours,
    ROUND(SUM(status_duration_seconds) / 86400.0, 2) AS Total_Days,
    MIN(status_start) AS First_Entered_At,
    MAX(status_end) AS Last_Exited_At
  FROM status_duration_rows
  GROUP BY Ticket_Key, status_label
),
status_summary_agg AS (
  SELECT
    Ticket_Key,
    ARRAY_AGG(
      STRUCT(
        status_label AS Status,
        Status_Entry_Count,
        Total_Seconds,
        Total_Minutes,
        Total_Hours,
        Total_Days,
        First_Entered_At,
        Last_Exited_At
      )
      ORDER BY First_Entered_At, status_label
    ) AS Status_Summary
  FROM status_summary_by_status
  GROUP BY Ticket_Key
),
changelog_agg AS (
  SELECT
    ch.Issue_Key,
    COUNT(*) AS Changelog_Count,
    COUNTIF(LOWER(COALESCE(ch.Changed_Field, 'status')) = 'assignee') AS Assignee_Change_Count,
    MAX(ch.Transition_Timestamp) AS Last_Transition_At,
    STRING_AGG(DISTINCT ch.Transitioned_To, ' ??? ' ORDER BY ch.Transitioned_To) AS Distinct_Transition_Targets,
    STRING_AGG(DISTINCT COALESCE(ch.Changed_Field, 'status'), ', ' ORDER BY COALESCE(ch.Changed_Field, 'status')) AS Distinct_Changed_Fields,
    ARRAY_AGG(
      STRUCT(
        ch.History_ID,
        ch.Transition_Timestamp,
        ch.Changed_Field,
        ch.From_Value,
        ch.To_Value,
        ch.Transitioned_From,
        ch.Transitioned_To,
        ch.Transitioned_By_Account_ID,
        ch.Transitioned_By_Display_Name,
        ch.SyncTime
      )
      ORDER BY ch.Transition_Timestamp DESC
    ) AS Changelog,
    ARRAY_AGG(
      STRUCT(
        ch.History_ID,
        ch.Transition_Timestamp,
        ch.Changed_Field,
        ch.From_Value,
        ch.To_Value,
        ch.Transitioned_From,
        ch.Transitioned_To,
        ch.Transitioned_By_Account_ID,
        ch.Transitioned_By_Display_Name,
        ch.SyncTime
      )
      ORDER BY ch.Transition_Timestamp DESC
      LIMIT 1
    )[OFFSET(0)] AS Last_Change
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` ch
  WHERE REGEXP_CONTAINS(COALESCE(ch.Issue_Key, ''), r'^VVT-')
  GROUP BY ch.Issue_Key
)
SELECT
  v.*,

  -- Comment summaries for charts/tables
  COALESCE(c.Comment_Count, 0) AS Comment_Count,
  c.Last_Comment_At,
  c.Comment_Authors,
  c.Last_Comment.Comment_ID AS Last_Comment_ID,
  c.Last_Comment.Author_Display_Name AS Last_Comment_Author,
  c.Last_Comment.Created AS Last_Comment_Created,
  c.Last_Comment.Updated AS Last_Comment_Updated,
  c.Last_Comment.Visibility_Type AS Last_Comment_Visibility_Type,
  c.Last_Comment.Visibility_Value AS Last_Comment_Visibility_Value,
  c.Last_Comment.Body AS Last_Comment_Body,
  SUBSTR(c.Last_Comment.Body, 1, 500) AS Last_Comment_Preview,

  -- Status timing summaries for charts/tables
  COALESCE(sd.Status_Interval_Count, 0) AS Status_Interval_Count,
  COALESCE(sd.Total_Status_Duration_Seconds, 0) AS Total_Status_Duration_Seconds,
  COALESCE(sd.Total_Status_Duration_Minutes, 0) AS Total_Status_Duration_Minutes,
  COALESCE(sd.Total_Status_Duration_Hours, 0) AS Total_Status_Duration_Hours,
  COALESCE(sd.Total_Status_Duration_Days, 0) AS Total_Status_Duration_Days,

  sd.Seconds_Backlog AS Seconds_Backlog,
  ROUND(sd.Seconds_Backlog / 60.0, 2) AS Minutes_Backlog,
  ROUND(sd.Seconds_Backlog / 3600.0, 2) AS Hours_Backlog,
  ROUND(sd.Seconds_Backlog / 86400.0, 2) AS Days_Backlog,

  sd.Seconds_In_Progress AS Seconds_In_Progress,
  ROUND(sd.Seconds_In_Progress / 60.0, 2) AS Minutes_In_Progress,
  ROUND(sd.Seconds_In_Progress / 3600.0, 2) AS Hours_In_Progress,
  ROUND(sd.Seconds_In_Progress / 86400.0, 2) AS Days_In_Progress,

  sd.Seconds_Waiting_For_Feedback AS Seconds_Waiting_For_Feedback,
  ROUND(sd.Seconds_Waiting_For_Feedback / 60.0, 2) AS Minutes_Waiting_For_Feedback,
  ROUND(sd.Seconds_Waiting_For_Feedback / 3600.0, 2) AS Hours_Waiting_For_Feedback,
  ROUND(sd.Seconds_Waiting_For_Feedback / 86400.0, 2) AS Days_Waiting_For_Feedback,

  -- Active verification-team time excluding Waiting For Feedback
  sd.Active_Verification_Time_Seconds AS Active_Verification_Time_Seconds,
  ROUND(sd.Active_Verification_Time_Seconds / 60.0, 2) AS Active_Verification_Time_Minutes,
  ROUND(sd.Active_Verification_Time_Seconds / 3600.0, 2) AS Active_Verification_Time_Hours,
  ROUND(sd.Active_Verification_Time_Seconds / 86400.0, 2) AS Active_Verification_Time_Days,

  sd.Seconds_Acceptance AS Seconds_Acceptance,
  ROUND(sd.Seconds_Acceptance / 60.0, 2) AS Minutes_Acceptance,
  ROUND(sd.Seconds_Acceptance / 3600.0, 2) AS Hours_Acceptance,
  ROUND(sd.Seconds_Acceptance / 86400.0, 2) AS Days_Acceptance,

  sd.Seconds_Rejected AS Seconds_Rejected,
  ROUND(sd.Seconds_Rejected / 60.0, 2) AS Minutes_Rejected,
  ROUND(sd.Seconds_Rejected / 3600.0, 2) AS Hours_Rejected,
  ROUND(sd.Seconds_Rejected / 86400.0, 2) AS Days_Rejected,

  sd.Seconds_Pending AS Seconds_Pending,
  ROUND(sd.Seconds_Pending / 60.0, 2) AS Minutes_Pending,
  ROUND(sd.Seconds_Pending / 3600.0, 2) AS Hours_Pending,
  ROUND(sd.Seconds_Pending / 86400.0, 2) AS Days_Pending,

  -- Changelog summaries for charts/tables
  COALESCE(ch.Changelog_Count, 0) AS Changelog_Count,
  COALESCE(ch.Assignee_Change_Count, 0) AS Assignee_Change_Count,
  ch.Last_Transition_At,
  ch.Distinct_Transition_Targets,
  ch.Distinct_Changed_Fields,
  ch.Last_Change.History_ID AS Last_Change_History_ID,
  ch.Last_Change.Transition_Timestamp AS Last_Change_Timestamp,
  ch.Last_Change.Transitioned_From AS Last_Transition_From,
  ch.Last_Change.Transitioned_To AS Last_Transition_To,
  ch.Last_Change.Transitioned_By_Display_Name AS Last_Transition_By,

  -- Drill-through arrays
  ss.Status_Summary,
  sd.Status_Durations,
  c.Comments,
  ch.Changelog
FROM vvt_tickets v
LEFT JOIN status_duration_agg sd
  ON sd.Ticket_Key = v.Ticket_Key
LEFT JOIN status_summary_agg ss
  ON ss.Ticket_Key = v.Ticket_Key
LEFT JOIN comments_agg c
  ON c.Issue_Key = v.Ticket_Key
LEFT JOIN changelog_agg ch
  ON ch.Issue_Key = v.Ticket_Key
ORDER BY v.Created DESC
