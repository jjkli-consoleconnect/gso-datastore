-- Shift-level snapshot (scheduled hourly): per-actor creation, closure, and worklog counts per shift
-- Each NOC has their own shift times (GMT+0)
WITH shift_config AS (
  SELECT noc, shift_name, start_hour, end_hour
  FROM UNNEST([
    STRUCT('GSOC TX - HK' AS noc, 'Morning' AS shift_name, 8 AS start_hour, 14 AS end_hour),
    STRUCT('GSOC TX - HK', 'Afternoon', 14, 23),
    STRUCT('GSOC TX - HK', 'Evening', 23, 8),
    STRUCT('HKNOC', 'Morning', 8, 16),
    STRUCT('HKNOC', 'Afternoon', 16, 23),
    STRUCT('HKNOC', 'Evening', 23, 8),
    STRUCT('GSOC TX - PH', 'Morning', 7, 15),
    STRUCT('GSOC TX - PH', 'Afternoon', 15, 23),
    STRUCT('GSOC TX - PH', 'Evening', 23, 7),
    STRUCT('FMC', 'Morning', 8, 14),
    STRUCT('FMC', 'Afternoon', 14, 23),
    STRUCT('FMC', 'Evening', 23, 8),
    STRUCT('SES', 'Morning', 8, 17),  -- 0815 rounded to 08
    STRUCT('SES', 'Afternoon', 17, 0),
    STRUCT('SES', 'Evening', 0, 8),
    STRUCT('Console Connect', 'Morning', 7, 15),
    STRUCT('Console Connect', 'Afternoon', 15, 23),
    STRUCT('Console Connect', 'Evening', 23, 7),
    STRUCT('VAS NOC', 'Morning', 7, 15),
    STRUCT('VAS NOC', 'Afternoon', 15, 23),
    STRUCT('VAS NOC', 'Evening', 23, 7),
    STRUCT('GSOC', 'Morning', 8, 14),
    STRUCT('GSOC', 'Afternoon', 14, 23),
    STRUCT('GSOC', 'Evening', 23, 8),
    STRUCT('PHSOC', 'Morning', 7, 15),
    STRUCT('PHSOC', 'Afternoon', 15, 23),
    STRUCT('PHSOC', 'Evening', 23, 7),
    STRUCT('ICX', 'Morning', 8, 14),
    STRUCT('ICX', 'Afternoon', 14, 23),
    STRUCT('ICX', 'Evening', 23, 8)
  ])
),
current_time AS (
  SELECT CURRENT_TIMESTAMP() AS now
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
    Shift_Name,
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
      hd.Submit_Date AS Date,
      -- Calculate shift based on NOC-specific shift config
      sc.shift_name AS Shift_Name,
      CASE
        WHEN sc.shift_name IS NOT NULL THEN 
          CONCAT(
            FORMAT_TIMESTAMP('%Y-%m-%d', 
              CASE 
                WHEN sc.end_hour < sc.start_hour AND EXTRACT(HOUR FROM hd.Submit_Date) < sc.end_hour 
                THEN TIMESTAMP_SUB(hd.Submit_Date, INTERVAL 1 DAY)
                ELSE hd.Submit_Date
              END
            ),
            ' - ',
            CASE sc.shift_name
              WHEN 'Morning' THEN '1 Morning'
              WHEN 'Afternoon' THEN '2 Afternoon'
              WHEN 'Evening' THEN '3 Evening'
            END
          )
        ELSE NULL
      END AS Shift
    FROM `GSO.HelpDeskAllNOC` AS hd
    LEFT JOIN shift_config sc
      ON hd.Assigned_Group = sc.noc
      AND (
        (sc.end_hour > sc.start_hour AND EXTRACT(HOUR FROM hd.Submit_Date) >= sc.start_hour AND EXTRACT(HOUR FROM hd.Submit_Date) < sc.end_hour)
        OR (sc.end_hour < sc.start_hour AND (EXTRACT(HOUR FROM hd.Submit_Date) >= sc.start_hour OR EXTRACT(HOUR FROM hd.Submit_Date) < sc.end_hour))
      )
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
    Shift_Name,
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
      hd.Closed_Date AS Date,
      -- Calculate shift based on NOC-specific shift config
      sc.shift_name AS Shift_Name,
      CASE
        WHEN sc.shift_name IS NOT NULL THEN 
          CONCAT(
            FORMAT_TIMESTAMP('%Y-%m-%d', 
              CASE 
                WHEN sc.end_hour < sc.start_hour AND EXTRACT(HOUR FROM hd.Closed_Date) < sc.end_hour 
                THEN TIMESTAMP_SUB(hd.Closed_Date, INTERVAL 1 DAY)
                ELSE hd.Closed_Date
              END
            ),
            ' - ',
            CASE sc.shift_name
              WHEN 'Morning' THEN '1 Morning'
              WHEN 'Afternoon' THEN '2 Afternoon'
              WHEN 'Evening' THEN '3 Evening'
            END
          )
        ELSE NULL
      END AS Shift
    FROM `GSO.HelpDeskAllNOC` AS hd
    LEFT JOIN shift_config sc
      ON hd.Assigned_Group = sc.noc
      AND (
        (sc.end_hour > sc.start_hour AND EXTRACT(HOUR FROM hd.Closed_Date) >= sc.start_hour AND EXTRACT(HOUR FROM hd.Closed_Date) < sc.end_hour)
        OR (sc.end_hour < sc.start_hour AND (EXTRACT(HOUR FROM hd.Closed_Date) >= sc.start_hour OR EXTRACT(HOUR FROM hd.Closed_Date) < sc.end_hour))
      )
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
    Shift_Name,
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
      CASE 
        WHEN wl.WorkLog_Submitter = 'AR_ESCALATOR' THEN NULLIF(TRIM(hd.Assignee), '')
        ELSE NULLIF(TRIM(wl.WorkLog_Submitter), '')
      END AS Work_Log_Submitter,
      wl.Last_Modified_Date AS WorkLog_Last_Modified_Date,
      wl.Last_Modified_By AS WorkLog_Last_Modified_By,
      wl.ExtractedDescription,
      wl.inserted_at,
      wl.WorkLog_Submit_Date AS Date,
      -- Calculate shift based on NOC-specific shift config
      sc.shift_name AS Shift_Name,
      CASE
        WHEN sc.shift_name IS NOT NULL THEN 
          CONCAT(
            FORMAT_TIMESTAMP('%Y-%m-%d', 
              CASE 
                WHEN sc.end_hour < sc.start_hour AND EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) < sc.end_hour 
                THEN TIMESTAMP_SUB(wl.WorkLog_Submit_Date, INTERVAL 1 DAY)
                ELSE wl.WorkLog_Submit_Date
              END
            ),
            ' - ',
            CASE sc.shift_name
              WHEN 'Morning' THEN '1 Morning'
              WHEN 'Afternoon' THEN '2 Afternoon'
              WHEN 'Evening' THEN '3 Evening'
            END
          )
        ELSE NULL
      END AS Shift
    FROM `GSO.WorkLogAllNOC` AS wl
    INNER JOIN `GSO.HelpDeskAllNOC` AS hd
      ON wl.Incident_Number = hd.Incident_Number
    LEFT JOIN shift_config sc
      ON hd.Assigned_Group = sc.noc
      AND (
        (sc.end_hour > sc.start_hour AND EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) >= sc.start_hour AND EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) < sc.end_hour)
        OR (sc.end_hour < sc.start_hour AND (EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) >= sc.start_hour OR EXTRACT(HOUR FROM wl.WorkLog_Submit_Date) < sc.end_hour))
      )
    WHERE wl.WorkLog_Submit_Date IS NOT NULL
      AND hd.Assigned_Group != 'Quality Assurance' AND hd.Status != 'Cancelled'
      AND NOT REGEXP_CONTAINS(IFNULL(wl.ExtractedDescription, ''), '(?i)JIRA status change,|From:\\s*globalhelpdesk@pccwglobal\\.com|To:\\s*gsocph@pccwglobal\\.com|Supervisor reviewed')
  ) AS work_logs
),
enriched AS (
  SELECT
    base_events.*,
    -- Normalize name: prefer Creation, then Closure, then WorkLog submitter, then Assignee; strip commas and collapse whitespace
    TRIM(REGEXP_REPLACE(REGEXP_REPLACE(
      COALESCE(base_events.Creation_FullName, base_events.Closure_FullName, base_events.Work_Log_Submitter, base_events.Assignee),
      r",[ ]*", " "
    ), r"\s+", " ")) AS Actor_FullName,
    CASE WHEN base_events.Event_Type = 'WorkLog' THEN base_events.WorkLog_ID ELSE base_events.Incident_Number END AS Count_Key,
    -- Format effort details: show event type name for creations/closures, or worklog details
    CASE 
      WHEN base_events.Event_Type = 'Creation' THEN 'Ticket Creation'
      WHEN base_events.Event_Type = 'Closure' THEN 'Ticket Closure'
      WHEN base_events.Event_Type = 'WorkLog' THEN CONCAT('WorkLog: ', IFNULL(base_events.ExtractedDescription, 'N/A'), ' [Type: ', IFNULL(base_events.Work_Log_Type, 'N/A'), ']')
    END AS EffortDescription
  FROM base_events
  WHERE base_events.Shift IS NOT NULL  -- Only include events with valid shifts
),
current_shift_boundary AS (
  SELECT
    TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY) AS today_start,
    TIMESTAMP_ADD(TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY), INTERVAL 1 DAY) AS tomorrow_start,
    TIMESTAMP_SUB(TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY), INTERVAL 1 DAY) AS yesterday_start
)
SELECT
  e.Actor_FullName,
  e.NOC,
  e.CaseType,
  e.Status,
  e.Shift AS ShiftSnapshot,
  EXTRACT(DATE FROM MIN(e.Date)) AS Snapshot_Date,
  CURRENT_TIMESTAMP() AS Snapshot_Timestamp,
  FORMAT_TIMESTAMP('%a', MIN(e.Date)) AS DoW,
  COUNTIF(e.Event_Type = 'WorkLog') AS WorkLog_Count,
  COUNTIF(e.Event_Type = 'Creation') AS Creation_Count,
  COUNTIF(e.Event_Type = 'Closure') AS Closure_Count,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'WorkLog' THEN e.WorkLog_ID END) AS WorkLog_Distinct,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'Creation' THEN e.Incident_Number END) AS Creation_Tickets,
  COUNT(DISTINCT CASE WHEN e.Event_Type = 'Closure' THEN e.Incident_Number END) AS Closure_Tickets,
  COUNT(DISTINCT e.Incident_Number) AS Tickets_Supported,
  STRING_AGG(DISTINCT e.Incident_Number, ', ' ORDER BY e.Incident_Number) AS Tickets_List,
  STRING_AGG(DISTINCT CONCAT(e.Incident_Number, ' | ', e.CaseType), '\n' ORDER BY CONCAT(e.Incident_Number, ' | ', e.CaseType)) AS Ticket_Details,
  STRING_AGG(DISTINCT e.EffortDescription, ' | ' ORDER BY e.EffortDescription) AS EffortDetails,
  EXTRACT(HOUR FROM CURRENT_TIMESTAMP()) AS Snapshot_Hour,
  CURRENT_DATETIME() AS Snapshot_DateTime
FROM enriched e
CROSS JOIN current_shift_boundary csb
WHERE 
  -- Include events from last 48 hours to catch all active shifts
  e.Date >= csb.yesterday_start
  AND e.Date < csb.tomorrow_start
GROUP BY Actor_FullName, NOC, CaseType, Status, ShiftSnapshot
ORDER BY ShiftSnapshot, Actor_FullName;