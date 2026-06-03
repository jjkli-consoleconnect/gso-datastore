WITH base_worklogs AS (
  SELECT
    w.WorkLog_ID,
    w.Incident_Number,
    w.WorkLog_Type,
    w.WorkLog_Submitter,
    w.WorkLog_Submit_Date,
    w.ExtractedDescription,
    h.Assigned_Group,
    CASE
      WHEN EXTRACT(HOUR FROM w.WorkLog_Submit_Date) BETWEEN 0 AND 6
        THEN FORMAT_TIMESTAMP('%Y-%m-%d', w.WorkLog_Submit_Date) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM w.WorkLog_Submit_Date) BETWEEN 7 AND 14
        THEN FORMAT_TIMESTAMP('%Y-%m-%d', w.WorkLog_Submit_Date) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM w.WorkLog_Submit_Date) BETWEEN 15 AND 22
        THEN FORMAT_TIMESTAMP('%Y-%m-%d', w.WorkLog_Submit_Date) || ' - 3 Evening'
      ELSE FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_ADD(w.WorkLog_Submit_Date, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS Shift
  FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC` w
  JOIN `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` h
    ON h.Incident_Number = w.Incident_Number
  WHERE EXTRACT(YEAR FROM w.WorkLog_Submit_Date) = 2026
    AND w.WorkLog_Submitter NOT IN ('apiadmin', 'aradmin', 'AR_ESCALATOR')
    AND h.Assigned_Group IN ('PHSOC', 'Console Connect', 'VAS NOC', 'Bel NOC')
),
ranked AS (
  SELECT
    bw.*,
    ROW_NUMBER() OVER (
      PARTITION BY bw.Shift, bw.WorkLog_Submitter
      ORDER BY bw.WorkLog_Submit_Date, bw.WorkLog_ID
    ) AS rn_first,
    ROW_NUMBER() OVER (
      PARTITION BY bw.Shift, bw.WorkLog_Submitter
      ORDER BY bw.WorkLog_Submit_Date DESC, bw.WorkLog_ID DESC
    ) AS rn_last,
    MIN(bw.WorkLog_Submit_Date) OVER (
      PARTITION BY bw.Shift, bw.WorkLog_Submitter
    ) AS shift_submitter_first_worklog_time,
    MAX(bw.WorkLog_Submit_Date) OVER (
      PARTITION BY bw.Shift, bw.WorkLog_Submitter
    ) AS shift_submitter_last_worklog_time,
    COUNT(*) OVER (
      PARTITION BY bw.Shift, bw.WorkLog_Submitter
    ) AS shift_submitter_worklog_count
  FROM base_worklogs bw
)
SELECT
  Shift,
  WorkLog_ID,
  Incident_Number,
  WorkLog_Type,
  WorkLog_Submitter,
  WorkLog_Submit_Date,
  ExtractedDescription,
  Assigned_Group,
  shift_submitter_worklog_count,
  shift_submitter_first_worklog_time,
  shift_submitter_last_worklog_time,
  rn_first AS shift_submitter_worklog_seq_asc,
  rn_last AS shift_submitter_worklog_seq_desc,
  IF(rn_first = 1, TRUE, FALSE) AS is_first_worklog_of_shift_for_submitter,
  IF(rn_last = 1, TRUE, FALSE) AS is_last_worklog_of_shift_for_submitter,
  CASE
    WHEN rn_first = 1 AND rn_last = 1 THEN 'ONLY'
    WHEN rn_first = 1 THEN 'FIRST'
    WHEN rn_last = 1 THEN 'LAST'
    ELSE 'MIDDLE'
  END AS shift_position_flag
FROM ranked
ORDER BY Shift, WorkLog_Submitter, WorkLog_Submit_Date, WorkLog_ID
