WITH base AS (
  SELECT
    COALESCE(NULLIF(Assignee, ''), NULLIF(Submitter, ''), NULLIF(Closed_By, '')) AS Person_Name,
    TIMESTAMP(
      DATE(
        TIMESTAMP(
          COALESCE(
            Closed_Date,
            LastResolvedDate,
            Submit_Date,
            Reported_Date
          )
        ),
        'UTC'
      ),
      'UTC'
    ) AS KPI_Timestamp_UTC,
    DATE(
      TIMESTAMP(
        COALESCE(
          Closed_Date,
          LastResolvedDate,
          Submit_Date,
          Reported_Date
        )
      ),
      'UTC'
    ) AS KPI_Date_UTC,
    Assigned_Group,
    FRT_Minutes,
    FRT_PassFail,
    FRT_InScope,
    SRT_Minutes,
    SRT_PassFail,
    SRT_InScope,
    MTTR_Minutes,
    MTTR_PassFail,
    MTTR_InScope,
    LSR_PassFail,
    LSR_InScope,
    ClosedTickets_InScope,
    KPI_CompositeScore
  FROM `pccw-internal-virt-agent-uat.GSO.Tier1KPI`
  WHERE COALESCE(NULLIF(Assignee, ''), NULLIF(Submitter, ''), NULLIF(Closed_By, '')) IS NOT NULL
),
daily AS (
  SELECT
    Person_Name,
    KPI_Timestamp_UTC,
    Assigned_Group,

    AVG(FRT_Minutes) AS FRT_AvgMinutes,
    COUNTIF(FRT_InScope = 1) AS FRT_InScope_Count,
    COUNTIF(FRT_PassFail = 'PASS') AS FRT_Pass_Count,
    ROUND(SAFE_DIVIDE(COUNTIF(FRT_PassFail = 'PASS'), COUNTIF(FRT_InScope = 1)) * 100, 2) AS FRT_CompliancePct,

    AVG(SRT_Minutes) AS SRT_AvgMinutes,
    COUNTIF(SRT_InScope = 1) AS SRT_InScope_Count,
    COUNTIF(SRT_PassFail = 'PASS') AS SRT_Pass_Count,
    ROUND(SAFE_DIVIDE(COUNTIF(SRT_PassFail = 'PASS'), COUNTIF(SRT_InScope = 1)) * 100, 2) AS SRT_CompliancePct,

    AVG(MTTR_Minutes) AS MTTR_AvgMinutes,
    COUNTIF(MTTR_InScope = 1) AS MTTR_InScope_Count,
    COUNTIF(MTTR_PassFail = 'PASS') AS MTTR_Pass_Count,
    ROUND(SAFE_DIVIDE(COUNTIF(MTTR_PassFail = 'PASS'), COUNTIF(MTTR_InScope = 1)) * 100, 2) AS MTTR_CompliancePct,

    COUNTIF(LSR_InScope = 1) AS LSR_InScope_Count,
    COUNTIF(LSR_PassFail = 'PASS') AS LSR_Pass_Count,
    ROUND(SAFE_DIVIDE(COUNTIF(LSR_PassFail = 'PASS'), COUNTIF(LSR_InScope = 1)) * 100, 2) AS LSR_Pct,

    COUNTIF(ClosedTickets_InScope = 1) AS ClosedTickets_Count,

    AVG(KPI_CompositeScore) AS KPI_CompositeScore_Avg
  FROM base
  GROUP BY Person_Name, KPI_Timestamp_UTC, Assigned_Group
)
SELECT
  Person_Name,
  KPI_Timestamp_UTC,
  Assigned_Group,

  FRT_AvgMinutes,
  FRT_InScope_Count,
  FRT_Pass_Count,
  FRT_CompliancePct,
  CASE
    WHEN FRT_InScope_Count = 0 THEN NULL
    WHEN FRT_CompliancePct < 92 THEN 1
    WHEN FRT_CompliancePct < 93 THEN 2
    WHEN FRT_CompliancePct < 94 THEN 3
    WHEN FRT_CompliancePct < 95 THEN 4
    WHEN FRT_CompliancePct < 96 THEN 5
    WHEN FRT_CompliancePct < 97 THEN 6
    ELSE 7
  END AS FRT_Rating,

  SRT_AvgMinutes,
  SRT_InScope_Count,
  SRT_Pass_Count,
  SRT_CompliancePct,
  CASE
    WHEN SRT_InScope_Count = 0 THEN NULL
    WHEN SRT_CompliancePct < 92 THEN 1
    WHEN SRT_CompliancePct < 93 THEN 2
    WHEN SRT_CompliancePct < 94 THEN 3
    WHEN SRT_CompliancePct < 95 THEN 4
    WHEN SRT_CompliancePct < 96 THEN 5
    WHEN SRT_CompliancePct < 97 THEN 6
    ELSE 7
  END AS SRT_Rating,

  MTTR_AvgMinutes,
  MTTR_InScope_Count,
  MTTR_Pass_Count,
  MTTR_CompliancePct,
  CASE
    WHEN MTTR_InScope_Count = 0 OR MTTR_AvgMinutes IS NULL THEN NULL
    WHEN MTTR_AvgMinutes < 45 THEN 7
    WHEN MTTR_AvgMinutes < 60 THEN 6
    WHEN MTTR_AvgMinutes < 75 THEN 5
    WHEN MTTR_AvgMinutes < 90 THEN 4
    WHEN MTTR_AvgMinutes < 105 THEN 3
    WHEN MTTR_AvgMinutes < 150 THEN 2
    ELSE 1
  END AS MTTR_Rating,

  LSR_InScope_Count,
  LSR_Pass_Count,
  LSR_Pct,
  CASE
    WHEN LSR_InScope_Count = 0 THEN NULL
    WHEN LSR_Pct < 65 THEN 1
    WHEN LSR_Pct < 70 THEN 2
    WHEN LSR_Pct < 75 THEN 3
    WHEN LSR_Pct < 80 THEN 4
    WHEN LSR_Pct < 85 THEN 5
    WHEN LSR_Pct < 90 THEN 6
    ELSE 7
  END AS LSR_Rating,

  ClosedTickets_Count,
  CASE
    WHEN ClosedTickets_Count < 50 THEN 1
    WHEN ClosedTickets_Count < 70 THEN 2
    WHEN ClosedTickets_Count < 90 THEN 3
    WHEN ClosedTickets_Count < 105 THEN 4
    WHEN ClosedTickets_Count < 120 THEN 5
    WHEN ClosedTickets_Count < 135 THEN 6
    ELSE 7
  END AS ClosedTickets_Rating,

  KPI_CompositeScore_Avg
FROM daily
