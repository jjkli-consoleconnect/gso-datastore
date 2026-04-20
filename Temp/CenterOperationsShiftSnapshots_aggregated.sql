-- Aggregated shift snapshot: per-actor creation, closure, and worklog counts
WITH boundaries AS (
  SELECT TIMESTAMP_TRUNC(@shift_end, DAY) + INTERVAL d DAY + INTERVAL h HOUR AS boundary
  FROM UNNEST([-1, 0, 1]) AS d
  CROSS JOIN UNNEST([7, 15, 23]) AS h
),
shift_window AS (
  SELECT
    shift_end,
    shift_end - INTERVAL 8 HOUR AS shift_start
  FROM (
    SELECT (
      SELECT boundary
      FROM boundaries
      WHERE boundary <= @shift_end
      ORDER BY boundary DESC
      LIMIT 1
    ) AS shift_end
  )
),
base_events AS (
  SELECT
    Incident_Number,
    Status,
    CaseType,
    NOC,
    Categorization_Tier_1,
    Categorization_Tier_2,
    Categorization_Tier_3,
    GCSC_1st_Customer_Update,
    GCSC_2nd_Customer_Update,
    GCSC_3rd_Customer_Update,
    Initial_Response_Time,
    Second_Response_Time,
    Third_Response_Time,
    Prod_ID,
    Fault_Cause,
    Closed_Date,
    Submit_Date,
    Assignee,
    Closed_By,
    Submitter,
    TrueMTTR_mins,
    Cust_ID,
    Carrier,
    Customer_Name,
    SRno,
    LastResolvedDate,
    ReportedDate,
    RespondedDate,
    FaultCauseDetail,
    LastModifiedDate,
    ReportedBy,
    Product_Family,
    ProductDescription,
    GSMP_Circuit_ID,
    NULL AS Work_Log_Type,
    NULL AS WorkLog_ID,
    NULL AS WorkLog_Submit_Date,
    NULL AS Work_Log_Submitter,
    NULL AS WorkLog_Last_Modified_Date,
    NULL AS WorkLog_Last_Modified_By,
    NULL AS ExtractedDescription,
    NULL AS inserted_at,
    Shift,
    Date,
    NULLIF(TRIM(Submitter), '') AS Creation_FullName,
    NULL AS Closure_FullName,
    'Creation' AS Event_Type
  FROM (
    SELECT
      hd.Incident_Number,
      hd.Status,
      hd.CaseType,
      hd.Assigned_Group AS NOC,
      hd.Categorization_Tier_1,
      hd.Categorization_Tier_2,
      hd.Categorization_Tier_3,
      hd.GCSC_1st_Customer_Update,
      hd.GCSC_2nd_Customer_Update,
      hd.GCSC_3rd_Customer_Update,
      hd.Initial_Response_Time,
      hd.Second_Response_Time,
      hd.Third_Response_Time,
      hd.Prod_ID,
      hd.Fault_Cause,
      hd.Closed_Date,
      hd.Submit_Date,
      hd.Assignee,
      hd.Closed_By,
      hd.Submitter,
      hd.TrueMTTR_mins,
      hd.Cust_ID,
      hd.Carrier,
      hd.Customer_Name,
      hd.SRno,
      hd.LastResolvedDate,
      hd.ReportedDate,
      hd.RespondedDate,
      hd.FaultCauseDetail,
      hd.LastModifiedDate,
      hd.ReportedBy,
      hd.Product_Family,
      hd.ProductDescription,
      hd.GSMP_Circuit_ID,
      CASE
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 0 AND 5 THEN FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SUB(hd.Submit_Date, INTERVAL 1 DAY)) || ' - 3 Evening'
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 6 AND 13 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 1 Morning'
        WHEN EXTRACT(HOUR FROM hd.Submit_Date) BETWEEN 14 AND 21 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 2 Afternoon'
        ELSE FORMAT_TIMESTAMP('%Y-%m-%d', hd.Submit_Date) || ' - 3 Evening'
      END AS Shift,
      hd.Submit_Date AS Date
    FROM `GSO.HelpDeskAllNOC` AS hd
    WHERE hd.Assigned_Group != 'Quality Assurance' AND hd.Status != 'Cancelled'
  ) AS creation
  UNION ALL
  SELECT
    Incident_Number,
    Status,
    CaseType,
    NOC,
    Categorization_Tier_1,
    Categorization_Tier_2,
    Categorization_Tier_3,
    GCSC_1st_Customer_Update,
    GCSC_2nd_Customer_Update,
    GCSC_3rd_Customer_Update,
    Initial_Response_Time,
    Second_Response_Time,
    Third_Response_Time,
    Prod_ID,
    Fault_Cause,
    Closed_Date,
    Submit_Date,
    Assignee,
    Closed_By,
    Submitter,
    TrueMTTR_mins,
    Cust_ID,
    Carrier,
    Customer_Name,
    SRno,
    LastResolvedDate,
    ReportedDate,
    RespondedDate,
    FaultCauseDetail,
    LastModifiedDate,
    ReportedBy,
    Product_Family,
    ProductDescription,
    GSMP_Circuit_ID,
    NULL AS Work_Log_Type,
    NULL AS WorkLog_ID,
    NULL AS WorkLog_Submit_Date,
    NULL AS Work_Log_Submitter,
    NULL AS WorkLog_Last_Modified_Date,
    NULL AS WorkLog_Last_Modified_By,
    NULL AS ExtractedDescription,
    NULL AS inserted_at,
    Shift,
    Date,
    NULL AS Creation_FullName,
    Closure_FullName,
    'Closure' AS Event_Type
  FROM (
    SELECT
      hd.Incident_Number,
      hd.Status,
      hd.CaseType,
      hd.Assigned_Group AS NOC,
      hd.Categorization_Tier_1,
      hd.Categorization_Tier_2,
      hd.Categorization_Tier_3,
      hd.GCSC_1st_Customer_Update,
      hd.GCSC_2nd_Customer_Update,
      hd.GCSC_3rd_Customer_Update,
      hd.Initial_Response_Time,
      hd.Second_Response_Time,
      hd.Third_Response_Time,
      hd.Prod_ID,
      hd.Fault_Cause,
      hd.Closed_Date,
      hd.Submit_Date,
      hd.Assignee,
      hd.Closed_By,
      hd.Submitter,
      hd.TrueMTTR_mins,
      hd.Cust_ID,
      hd.Carrier,
      hd.Customer_Name,
      hd.SRno,
      hd.LastResolvedDate,
      hd.ReportedDate,
      hd.RespondedDate,
      hd.FaultCauseDetail,
      hd.LastModifiedDate,
      hd.ReportedBy,
      hd.Product_Family,
      hd.ProductDescription,
      hd.GSMP_Circuit_ID,
      NULLIF(TRIM(hd.Closed_By), '') AS Closure_FullName,
      CASE
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 0 AND 5 THEN FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SUB(hd.Closed_Date, INTERVAL 1 DAY)) || ' - 3 Evening'
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 6 AND 13 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 1 Morning'
        WHEN EXTRACT(HOUR FROM hd.Closed_Date) BETWEEN 14 AND 21 THEN FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 2 Afternoon'
        ELSE FORMAT_TIMESTAMP('%Y-%m-%d', hd.Closed_Date) || ' - 3 Evening'
      END AS Shift,
      hd.Closed_Date AS Date
    FROM `GSO.HelpDeskAllNOC` AS hd
    WHERE hd.Closed_Date IS NOT NULL AND hd.Assigned_Group != 'Quality Assurance' AND hd.Status != 'Cancelled'
  ) AS closure
  UNION ALL
  SELECT
    Incident_Number,
    Status,
    CaseType,
    NOC,
    Categorization_Tier_1,
    Categorization_Tier_2,
    Categorization_Tier_3,
    GCSC_1st_Customer_Update,
    GCSC_2nd_Customer_Update,
    GCSC_3rd_Customer_Update,
    Initial_Response_Time,
    Second_Response_Time,
    Third_Response_Time,
    Prod_ID,
    Fault_Cause,
    Closed_Date,
    Submit_Date,
    Assignee,
    Closed_By,
    Submitter,
    TrueMTTR_mins,
    Cust_ID,
    Carrier,
    Customer_Name,
    SRno,
    LastResolvedDate,
    ReportedDate,
    RespondedDate,
    FaultCauseDetail,
    LastModifiedDate,
    ReportedBy,
    Product_Family,
    ProductDescription,
    GSMP_Circuit_ID,
    Work_Log_Type,
    WorkLog_ID,
    WorkLog_Submit_Date,
    Work_Log_Submitter,
    WorkLog_Last_Modified_Date,
    WorkLog_Last_Modified_By,
    ExtractedDescription,
    inserted_at,
    Shift,
    Date,
    NULL AS Creation_FullName,
    NULL AS Closure_FullName,
    'WorkLog' AS Event_Type
  FROM (
    SELECT
      wl.Incident_Number,
      hd.Status,
      hd.CaseType,
      hd.Assigned_Group AS NOC,
      hd.Categorization_Tier_1,
      hd.Categorization_Tier_2,
      hd.Categorization_Tier_3,
      hd.GCSC_1st_Customer_Update,
      hd.GCSC_2nd_Customer_Update,
      hd.GCSC_3rd_Customer_Update,
      hd.Initial_Response_Time,
      hd.Second_Response_Time,
      hd.Third_Response_Time,
      hd.Prod_ID,
      hd.Fault_Cause,
      hd.Closed_Date,
      hd.Submit_Date,
      hd.Assignee,
      hd.Closed_By,
      hd.Submitter,
      hd.TrueMTTR_mins,
      hd.Cust_ID,
      hd.Carrier,
      hd.Customer_Name,
      hd.SRno,
      hd.LastResolvedDate,
      hd.ReportedDate,
      hd.RespondedDate,
      hd.FaultCauseDetail,
      hd.LastModifiedDate,
      hd.ReportedBy,
      hd.Product_Family,
      hd.ProductDescription,
      hd.GSMP_Circuit_ID,
      wl.WorkLog_Type AS Work_Log_Type,
      wl.WorkLog_ID,
      wl.WorkLog_Submit_Date,
      NULLIF(TRIM(hd.Assignee), '') AS Work_Log_Submitter,
      wl.Last_Modified_Date AS WorkLog_Last_Modified_Date,
      wl.Last_Modified_By AS WorkLog_Last_Modified_By,
      wl.ExtractedDescription,
      wl.inserted_at,
      CASE
        WHEN EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) BETWEEN 0 AND 5 THEN FORMAT_TIMESTAMP('%Y-%m-%d', TIMESTAMP_SUB(wl.WorkLog_Submit_Date, INTERVAL 1 DAY)) || ' - 3 Evening'
        WHEN EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) BETWEEN 6 AND 13 THEN FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLog_Submit_Date) || ' - 1 Morning'
        WHEN EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) BETWEEN 14 AND 21 THEN FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLog_Submit_Date) || ' - 2 Afternoon'
        ELSE FORMAT_TIMESTAMP('%Y-%m-%d', wl.WorkLog_Submit_Date) || ' - 3 Evening'
      END AS Shift,
      wl.WorkLog_Submit_Date AS Date
    FROM `GSO.WorkLogAllNOC` AS wl
    INNER JOIN `GSO.HelpDeskAllNOC` AS hd
      ON wl.Incident_Number = hd.Incident_Number
    WHERE wl.WorkLog_Submit_Date IS NOT NULL
      AND hd.Assigned_Group != 'Quality Assurance' AND hd.Status != 'Cancelled'
      AND NOT REGEXP_CONTAINS(IFNULL(wl.ExtractedDescription, ''), '(?i)JIRA status change,|From:\\s*globalhelpdesk@pccwglobal\\.com|To:\\s*gsocph@pccwglobal\\.com|Supervisor reviewed')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY wl.WorkLog_ID
      ORDER BY wl.WorkLog_Submit_Date DESC, wl.inserted_at DESC
    ) = 1
  ) AS work_logs
),
enriched AS (
  SELECT
    base_events.*,
    -- For WorkLog events, force attribution to ticket assignee (even if Work_Log_Submitter is a system name)
    COALESCE(base_events.Creation_FullName, base_events.Closure_FullName, base_events.Assignee) AS Actor_FullName,
    CASE WHEN base_events.Event_Type = 'WorkLog' THEN base_events.WorkLog_ID ELSE base_events.Incident_Number END AS Count_Key,
    -- Format effort details: show event type name for creations/closures, or worklog details
    CASE 
      WHEN base_events.Event_Type = 'Creation' THEN 'Ticket Creation'
      WHEN base_events.Event_Type = 'Closure' THEN 'Ticket Closure'
      WHEN base_events.Event_Type = 'WorkLog' THEN CONCAT('WorkLog: ', IFNULL(base_events.ExtractedDescription, 'N/A'), ' [Type: ', IFNULL(base_events.Work_Log_Type, 'N/A'), ']')
    END AS EffortDescription
  FROM base_events
)
SELECT
  e.Actor_FullName,
  e.NOC,
  e.CaseType,
  e.Status,
  CASE
    WHEN EXTRACT(HOUR FROM shift_window.shift_start) = 7 THEN FORMAT_TIMESTAMP('%Y-%m-%d', shift_window.shift_start) || ' - 1 Morning'
    WHEN EXTRACT(HOUR FROM shift_window.shift_start) = 15 THEN FORMAT_TIMESTAMP('%Y-%m-%d', shift_window.shift_start) || ' - 2 Afternoon'
    ELSE FORMAT_TIMESTAMP('%Y-%m-%d', shift_window.shift_start) || ' - 3 Evening'
  END AS ShiftSnapshot,
  DATE(shift_window.shift_start) AS Snapshot_Date,
  shift_window.shift_end AS Snapshot_Timestamp,
  FORMAT_TIMESTAMP('%a', shift_window.shift_start) AS DoW,
  COUNTIF(e.Event_Type = 'WorkLog') AS WorkLog_Count,
  COUNTIF(e.Event_Type = 'Creation') AS Creation_Count,
  COUNTIF(e.Event_Type = 'Closure') AS Closure_Count,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'WorkLog' THEN e.WorkLog_ID END) AS WorkLog_Distinct,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'Creation' THEN e.Incident_Number END) AS Creation_Tickets,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'Closure' THEN e.Incident_Number END) AS Closure_Tickets,
  COUNT(DISTINCT e.Incident_Number) AS Tickets_Supported,
  STRING_AGG(DISTINCT e.Incident_Number, ', ' ORDER BY e.Incident_Number) AS Tickets_List,
  STRING_AGG(DISTINCT CONCAT(e.Incident_Number, ' | ', e.CaseType), '\n' ORDER BY CONCAT(e.Incident_Number, ' | ', e.CaseType)) AS Ticket_Details,
  STRING_AGG(DISTINCT e.EffortDescription, ' | ' ORDER BY e.EffortDescription) AS EffortDetails
FROM enriched e
CROSS JOIN shift_window
WHERE e.Date >= shift_window.shift_start AND e.Date < shift_window.shift_end
GROUP BY Actor_FullName, NOC, CaseType, Status, ShiftSnapshot, Snapshot_Date, Snapshot_Timestamp, DoW
ORDER BY ShiftSnapshot, Actor_FullName;