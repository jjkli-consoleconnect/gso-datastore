SELECT
  -- Identity
  h.Incident_Number,
  h.SRno,
  h.Cust_ID,
  h.Customer_Name,
  h.Carrier,

  -- Ticket Classification
  h.CaseType,
  h.Status,
  h.TicketProcess,
  h.Priority,
  h.Urgency,
  h.Assigned_Group,
  h.Assignee,

  -- Categorization
  h.Categorization_Tier_1,
  h.Categorization_Tier_2,
  h.Categorization_Tier_3,
  h.Prod_ID,
  h.Product_Family,
  h.ProductDescription,
  h.Fault_Cause,
  h.AIFaultCause,

  -- Timestamps
  h.Reported_Date,
  h.Submit_Date,
  h.LastResolvedDate,
  h.Closed_Date,
  h.WorkLog_Type,
  h.WorkLog_Submitter,
  email_wl.EmailProgressUpdate_Count,
  email_wl.EmailProgressUpdate_First_Submitter,
  email_wl.EmailProgressUpdate_First_Submit_Date,
  h.GCSC_1st_Customer_Update,
  h.GCSC_2nd_Customer_Update,

  -- ─────────────────────────────────────────────────────────
  -- KPI 1: First Response Time (FRT)
  -- Scope : Incidents | Closed or Resolved | has Email Progress Update worklog
  -- SLA   : FRT ≤ 30 min → PASS  |  Target: 95%
  -- Weight: 8%
  -- ─────────────────────────────────────────────────────────
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
     AND h.GCSC_1st_Customer_Update IS NOT NULL
     AND h.Submit_Date IS NOT NULL
    THEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.Submit_Date, MINUTE)
    ELSE NULL
  END AS FRT_Minutes,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
     AND h.GCSC_1st_Customer_Update IS NOT NULL
     AND h.Submit_Date IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.Submit_Date, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE NULL
  END AS FRT_PassFail,

  -- 1 for in-scope tickets (denominator in Looker Studio)
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN 1
    ELSE NULL
  END AS FRT_InScope,

  -- ─────────────────────────────────────────────────────────
  -- KPI 2: Second Response Time (SRT)
  -- Scope : Incidents | Closed or Resolved | has Email Progress Update worklog
  -- SLA   : SRT ≤ 90 min → PASS  |  Target: 95%
  -- Weight: 7%
  -- ─────────────────────────────────────────────────────────
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN h.`2nd_Response_Minutes`
    ELSE NULL
  END AS SRT_Minutes,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN h.`2nd_Response_PassFail`
    ELSE NULL
  END AS SRT_PassFail,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN 1
    ELSE NULL
  END AS SRT_InScope,

  -- ─────────────────────────────────────────────────────────
  -- KPI 3: MTTR (Mean Time to Restore)
  -- Scope : Incidents | P1/P2 (Critical, High) | Closed or Resolved
  -- SLA   : MTTR ≤ 90 min → PASS  |  Target: 60%
  -- Weight: 15%
  -- ─────────────────────────────────────────────────────────
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Priority IN ('Critical', 'High')
     AND h.Status IN ('Resolved', 'Closed')
    THEN h.TrueMTTR_mins
    ELSE NULL
  END AS MTTR_Minutes,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Priority IN ('Critical', 'High')
     AND h.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN h.TrueMTTR_mins <= 90 THEN 'PASS' ELSE 'FAIL' END
    ELSE NULL
  END AS MTTR_PassFail,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Priority IN ('Critical', 'High')
     AND h.Status IN ('Resolved', 'Closed')
    THEN 1
    ELSE NULL
  END AS MTTR_InScope,

  -- ─────────────────────────────────────────────────────────
  -- Row-Level Scoring
  -- Each metric earns its weight (8/7/15) on PASS, 0 on FAIL,
  -- NULL when out of scope.
  -- Composite = earned_points / applicable_weight_total ╫ 100
  -- ─────────────────────────────────────────────────────────

  -- FRT score points (weight 8)
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
     AND h.GCSC_1st_Customer_Update IS NOT NULL
     AND h.Submit_Date IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.Submit_Date, MINUTE) <= 30 THEN 8
      ELSE 0
    END
    ELSE NULL
  END AS FRT_ScorePoints,

  -- SRT score points (weight 7)
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN CASE WHEN h.`2nd_Response_PassFail` = 'PASS' THEN 7 ELSE 0 END
    ELSE NULL
  END AS SRT_ScorePoints,

  -- MTTR score points (weight 15, P1+P2 only)
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Priority IN ('Critical', 'High')
     AND h.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN h.TrueMTTR_mins <= 90 THEN 15 ELSE 0 END
    ELSE NULL
  END AS MTTR_ScorePoints,

  -- ─────────────────────────────────────────────────────────
  -- MTTR Rating 1û7 (row-level, P1/P2 incidents only)
  -- 7 = <45 min  |  6 = <60 min  |  5 = <75 min
  -- 4 = <90 min  |  3 = <105 min |  2 = <120 min
  -- 1 = ≥150 min (>2h30m)
  -- ─────────────────────────────────────────────────────────
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Priority IN ('Critical', 'High')
     AND h.Status IN ('Resolved', 'Closed')
     AND h.TrueMTTR_mins IS NOT NULL
    THEN CASE
      WHEN h.TrueMTTR_mins <  45  THEN 7
      WHEN h.TrueMTTR_mins <  60  THEN 6
      WHEN h.TrueMTTR_mins <  75  THEN 5
      WHEN h.TrueMTTR_mins <  90  THEN 4
      WHEN h.TrueMTTR_mins < 105  THEN 3
      WHEN h.TrueMTTR_mins < 150  THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS MTTR_Rating,

  -- ─────────────────────────────────────────────────────────
  -- KPI 4: Level Solvable Rate (LSR)
  -- Scope : Incidents | Closed or Resolved
  -- SLA   : ≥80% resolved at assigned level (no Jira escalation)
  -- Weight: 10%
  -- Escalated = Remedy ticket has a linked Jira key in JIRA_HD
  -- ─────────────────────────────────────────────────────────

  -- Jira key(s) for escalated incidents
  jira_esc.Jira_Key AS Escalated_Jira_Key,
  jira_esc.Jira_Keys AS Escalated_Jira_Keys,

  -- Flag: 1 = escalated (Jira linked), 0 = not escalated
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN jira_esc.Jira_Key IS NOT NULL THEN 1 ELSE 0 END
    ELSE NULL
  END AS LSR_Escalated,

  -- PASS = resolved at level (not escalated)
  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN jira_esc.Jira_Key IS NULL THEN 'PASS' ELSE 'FAIL' END
    ELSE NULL
  END AS LSR_PassFail,

  CASE
    WHEN h.CaseType = 'Incident'
     AND h.Status IN ('Resolved', 'Closed')
    THEN 1
    ELSE NULL
  END AS LSR_InScope,

  -- LSR score points (weight 10)
  CASE
    WHEN h.CaseType = 'Incident' AND h.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN jira_esc.Jira_Key IS NULL THEN 10 ELSE 0 END
    ELSE NULL
  END AS LSR_ScorePoints,

  -- Composite weighted score % for this row
  -- Denominator = sum of weights for KPIs applicable to this ticket
  -- FRT/SRT weights apply only when incident has Email Progress Update worklog
  -- P1/P2: (FRT/SRT optional) + MTTR(15) + LSR(10)
  -- Other: (FRT/SRT optional) + LSR(10)
  CASE
    WHEN h.CaseType = 'Incident' AND h.Status IN ('Resolved', 'Closed')
      AND h.Priority IN ('Critical', 'High')
    THEN ROUND(
      (
        CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND h.GCSC_1st_Customer_Update IS NOT NULL
           AND h.Submit_Date IS NOT NULL
           AND TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.Submit_Date, MINUTE) <= 30
          THEN 8 ELSE 0 END
        + CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND h.`2nd_Response_PassFail` = 'PASS'
          THEN 7 ELSE 0 END
        + CASE WHEN h.TrueMTTR_mins <= 90 THEN 15 ELSE 0 END
        + CASE WHEN jira_esc.Jira_Key IS NULL THEN 10 ELSE 0 END
      ) /
      (
        CASE WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0 THEN 15 ELSE 0 END
        + 15
        + 10
      ) * 100, 2)
    WHEN h.CaseType = 'Incident' AND h.Status IN ('Resolved', 'Closed')
    THEN ROUND(
      (
        CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND h.GCSC_1st_Customer_Update IS NOT NULL
           AND h.Submit_Date IS NOT NULL
           AND TIMESTAMP_DIFF(h.GCSC_1st_Customer_Update, h.Submit_Date, MINUTE) <= 30
          THEN 8 ELSE 0 END
        + CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND h.`2nd_Response_PassFail` = 'PASS'
          THEN 7 ELSE 0 END
        + CASE WHEN jira_esc.Jira_Key IS NULL THEN 10 ELSE 0 END
      ) /
      (
        CASE WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0 THEN 15 ELSE 0 END
        + 10
      ) * 100, 2)
    ELSE NULL
  END AS KPI_CompositeScore,

  -- WorkLog Analytics
  h.WorkLog_Count,

  -- AI Fields
  h.AIFirstResponse,
  h.AIFirstResponseTimestamp,
  h.AIAtFault,
  h.AI_FaultDomain,
  h.AI_PrimarySymptom,
  h.AI_LikelyRootCause,
  h.AI_ConfidenceScore

FROM
  `pccw-internal-virt-agent-uat.GSO.HDWL` h

-- ─────────────────────────────────────────────────────────
-- LSR: detect escalation via linked Jira ticket
-- Any Remedy incident with a matching Jira ticket mapping
-- (i.e. Jira key exists) = escalated
-- ─────────────────────────────────────────────────────────
LEFT JOIN (
  SELECT
    remedy_incident AS Incident_Number,
    MIN(Key) AS Jira_Key,
    STRING_AGG(DISTINCT Key, ', ' ORDER BY Key) AS Jira_Keys
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` jt
  LEFT JOIN UNNEST(jt.RemedyTicketNumber) AS remedy_incident
  WHERE remedy_incident IS NOT NULL
    AND Key IS NOT NULL
    AND COALESCE(jt.IsDeleted, FALSE) = FALSE
  GROUP BY remedy_incident
) jira_esc
  ON jira_esc.Incident_Number = h.Incident_Number

LEFT JOIN (
  SELECT
    Incident_Number,
    COUNT(1) AS EmailProgressUpdate_Count,
    ARRAY_AGG(WorkLog_Submitter IGNORE NULLS ORDER BY WorkLog_Submit_Date ASC LIMIT 1)[SAFE_OFFSET(0)] AS EmailProgressUpdate_First_Submitter,
    ARRAY_AGG(WorkLog_Submit_Date IGNORE NULLS ORDER BY WorkLog_Submit_Date ASC LIMIT 1)[SAFE_OFFSET(0)] AS EmailProgressUpdate_First_Submit_Date
  FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC`
  WHERE REGEXP_REPLACE(UPPER(TRIM(WorkLog_Type)), r'[^A-Z0-9]+', '') = 'EMAILPROGRESSUPDATE'
  GROUP BY Incident_Number
) email_wl
  ON email_wl.Incident_Number = h.Incident_Number

WHERE
  -- One row per ticket
  (h.WorkLog_Sequence = 1 OR h.WorkLog_Sequence IS NULL)
  -- Assigned Group filter
  AND h.Assigned_Group IN ('Console Connect', 'GSOC', 'PHSOC', 'VAS NOC')

