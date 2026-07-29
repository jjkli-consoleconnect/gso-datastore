WITH base AS (
  SELECT
    h.*,
    REGEXP_REPLACE(UPPER(TRIM(h.Fault_Cause)), r'[^A-Z0-9]+', ' ') AS Normalized_Fault_Cause
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL` h
  WHERE (h.WorkLog_Sequence = 1 OR h.WorkLog_Sequence IS NULL)
    AND h.Assigned_Group IN ('Console Connect', 'GSOC', 'PHSOC', 'VAS NOC')
    AND h.Closed_Date IS NOT NULL
),
jira_esc AS (
  SELECT
    remedy_incident AS Incident_Number,
    MIN(Key) AS Jira_Key
  FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` jt
  LEFT JOIN UNNEST(jt.RemedyTicketNumber) AS remedy_incident
  WHERE remedy_incident IS NOT NULL
    AND Key IS NOT NULL
    AND COALESCE(jt.IsDeleted, FALSE) = FALSE
  GROUP BY remedy_incident
),
email_wl AS (
  SELECT
    Incident_Number,
    COUNT(1) AS EmailProgressUpdate_Count
  FROM `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC`
  WHERE REGEXP_REPLACE(UPPER(TRIM(WorkLog_Type)), r'[^A-Z0-9]+', '') = 'EMAILPROGRESSUPDATE'
  GROUP BY Incident_Number
),
worklog_details AS (
  SELECT
    h.Incident_Number,
    ARRAY_AGG(
      STRUCT(
        h.WorkLog_ID,
        h.WorkLog_Type,
        h.WorkLog_Submitter,
        h.WorkLog_Submit_Date,
        h.WorkLog_Sequence
      )
      ORDER BY h.WorkLog_Sequence, h.WorkLog_Submit_Date, h.WorkLog_ID
    ) AS WorkLog_Details
  FROM `pccw-internal-virt-agent-uat.GSO.HDWL` h
  WHERE h.WorkLog_ID IS NOT NULL
    AND h.Assigned_Group IN ('Console Connect', 'GSOC', 'PHSOC', 'VAS NOC')
    AND UPPER(h.WorkLog_Submitter) != 'AR_ESCALATOR'
    AND UPPER(h.WorkLog_Submitter) NOT LIKE '%ADMIN%'
    AND UPPER(h.WorkLog_Submitter) != 'REMEDY APPLICATION SERVICE'
  GROUP BY h.Incident_Number
),
mttr_allowed_fault_causes AS (
  SELECT cause
  FROM UNNEST([
    'ANYTHING INTERNAL NETWORK RELATED',
    'API FAILED REQUEST',
    'API ISSUE',
    'BACKHAUL',
    'BEST ROUTE',
    'CALLED NUMBER BLOCKED BY CARRIER LOCAL',
    'CALLING NUMBER BLOCKED BY CARRIER LOCAL',
    'CDR OR FILE TRANSFER ISSUE',
    'COMMERCIAL ISSUE',
    'CONFIG ISSUE RELATED',
    'CONFIGURATION PROBLEM',
    'CONNECTIVITY OUTAGE',
    'CONSOLE API ISSUE',
    'CONSOLE CONNECT CONNECTIVITY ISSUE',
    'CONSOLE CONNECT PLATFORM ISSUE',
    'CONSOLE CONNECT PORTAL ISSUE',
    'CONSOLE PLATFORM CODE ISSUE',
    'CONSOLE SECURITY ATTACK',
    'CONSOLE SERVICE LAYER ISSUE',
    'CODE BUG IN CONSOLE SERVICE LAYER',
    'CODE ERROR IN CONSOLE WORKFLOW',
    'CORE NETWORK HARDWARE ISSUE',
    'CORE PLATFORM NETWORK',
    'COVERAGE OR MOBILE NETWORK PROBLEM IN HONG KONG',
    'COVERAGE OR MOBILE NETWORK PROBLEM IN ROAMING COUNTRY',
    'CUSTOMER CONFIGURATION PROBLEM',
    'CUSTOMER EQUIPMENT',
    'DUPLICATE TICKET',
    'FAR END FAULT',
    'FIBER CUT',
    'FRONTIER STATION',
    'GENERAL SERVICE ENQUIRY',
    'HARDWARE ISSUE',
    'IOT API ISSUE',
    'IOT CDR OR FILE TRANSFER ISSUE',
    'IOT CONSOLE CONNECT CONNECTIVITY ISSUE',
    'IOT CONSOLE CONNECT PLATFORM ISSUE',
    'IOT CONSOLE CONNECT PORTAL ISSUE',
    'IOT COVERAGE OR MOBILE NETWORK PROBLEM IN HONG KONG',
    'IOT COVERAGE OR MOBILE NETWORK PROBLEM IN ROAMING COUNTRY',
    'IOT CUSTOMER CONFIGURATION PROBLEM',
    'IOT GENERAL SERVICE ENQUIRY',
    'IOT NETWORK CONNECTIVITY PROBLEM',
    'IOT NETWORK OR APN CONFIGURATION PROBLEM',
    'IOT PROVISIONING',
    'IOT SIM MANAGEMENT PORTAL ISSUE',
    'IOT SIM OR E SIM PLATFORM ISSUE',
    'IOT SIM PROVISIONING OR CONFIGURATION',
    'IOT SMS PLATFORM',
    'INC PCCW GLOBAL NETWORK INFRASTRUTURE',
    'INCIDENT API ISSUE',
    'INCIDENT CONFIG MISMATCH DUE TO INFLIGHT CHANGE',
    'INCIDENT CONSOLE FEATURE DEFICIENCY',
    'INCIDENT DIRTY FIBRE',
    'INCIDENT FAULTY EQUIPMENT EG PORT',
    'INCIDENT IP ADDRESS S GEO BLOCKED',
    'INCIDENT INTERFACE WAS UNPLUGGED',
    'INCIDENT LIGHT LEVELS LOW NOT WITHIN SPEC',
    'INCIDENT PLATFORM ISSUE CODE ERROR FUNCTIONALITY DEFICIENCY',
    'INCIDENT SECURITY ATTACK',
    'INCIDENT UNSTABLE CONNECTION',
    'INCIDENT WEB PAGE NOT REACHABLE',
    'INCOMPATIBLE MEDIA CONVERTER',
    'INTERNATIONAL LINK TRUNK OR SUBMARINE CABLE',
    'INTERNATIONAL PORTION FAULT BETWEEN TWO CABLE STATIONS COUNTRIES',
    'INTERNET CONNECTIVITY DOWN',
    'IPVPN BACKHAUL',
    'IPVPN CORE PLATFORM NETWORK',
    'IPVPN INTERNATIONAL LINK TRUNK OR SUBMARINE CABLE',
    'IPVPN LOCAL ITMC LOCAL TERRITORIAL LINK',
    'IPVPN LOCAL LOOP',
    'IPVPN RIGHT WHEN TEST',
    'IPVPN UNTRACED FAULT',
    'LOCAL ITMC LOCAL TERRITORIAL LINK',
    'LOCAL LOOP',
    'MAINTENANCE NOTIFICATION ERROR INTERNAL',
    'MAINTENANCE NOTIFICATION ERROR PARTNER',
    'MOBILITY CONFIGURATION PROBLEM',
    'MOBILITY NETWORK ISSUE',
    'NETWORK',
    'NETWORK CONNECTIVITY DOWN',
    'NETWORK CONNECTIVITY PROBLEM',
    'NETWORK ISSUE',
    'NETWORK OR APN CONFIGURATION PROBLEM',
    'NON CUSTOMER APPLICATION',
    'NON CUSTOMER EQUIPMENT FAILURE',
    'NON CUSTOMER FAULT ISSUES',
    'OTHERS INTERNAL HUMAN ERROR',
    'PARTNER NETWORK',
    'PCCW EQUIPMENT',
    'PEERING PARTNER',
    'PERFORMANCE',
    'PROLONGED MAINTENANCE',
    'PROVISIONING',
    'RIGHT WHEN TEST',
    'SCHEDULED MAINTENANCE NOT COMMUNICATED',
    'SIM MANAGEMENT PORTAL ISSUE',
    'SIM OR E SIM PLATFORM ISSUE',
    'SIM PROVISIONING OR CONFIGURATION',
    'SMS PLATFORM',
    'SPECIFIC DATA CENTER POP OUTAGE'
  ]) AS cause
)

SELECT
  base.Incident_Number,
  base.Assigned_Group,
  base.Assignee,
  base.Submitter AS Ticket_Submitter,
  base.Submit_Date,
  base.Closed_Date,
  base.Closed_By,
  worklog_details.WorkLog_Details,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
     AND base.GCSC_1st_Customer_Update IS NOT NULL
     AND base.Submit_Date IS NOT NULL
    THEN TIMESTAMP_DIFF(base.GCSC_1st_Customer_Update, base.Submit_Date, MINUTE)
    ELSE NULL
  END AS FRT_Minutes,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
     AND base.GCSC_1st_Customer_Update IS NOT NULL
     AND base.Submit_Date IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(base.GCSC_1st_Customer_Update, base.Submit_Date, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE NULL
  END AS FRT_PassFail,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN base.`2nd_Response_Minutes`
    ELSE NULL
  END AS SRT_Minutes,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
     AND COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
    THEN base.`2nd_Response_PassFail`
    ELSE NULL
  END AS SRT_PassFail,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Priority IN ('Critical', 'High')
     AND base.Status IN ('Resolved', 'Closed')
     AND base.Normalized_Fault_Cause IN (SELECT cause FROM mttr_allowed_fault_causes)
    THEN base.TrueMTTR_mins
    ELSE NULL
  END AS MTTR_Minutes,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Priority IN ('Critical', 'High')
     AND base.Status IN ('Resolved', 'Closed')
     AND base.Normalized_Fault_Cause IN (SELECT cause FROM mttr_allowed_fault_causes)
    THEN CASE WHEN base.TrueMTTR_mins <= 90 THEN 'PASS' ELSE 'FAIL' END
    ELSE NULL
  END AS MTTR_PassFail,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Priority IN ('Critical', 'High')
     AND base.Status IN ('Resolved', 'Closed')
     AND base.Normalized_Fault_Cause IN (SELECT cause FROM mttr_allowed_fault_causes)
     AND base.TrueMTTR_mins IS NOT NULL
    THEN CASE
      WHEN base.TrueMTTR_mins < 45 THEN 7
      WHEN base.TrueMTTR_mins < 60 THEN 6
      WHEN base.TrueMTTR_mins < 75 THEN 5
      WHEN base.TrueMTTR_mins < 90 THEN 4
      WHEN base.TrueMTTR_mins < 105 THEN 3
      WHEN base.TrueMTTR_mins < 150 THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS MTTR_Rating,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN jira_esc.Jira_Key IS NOT NULL THEN base.Incident_Number ELSE null END
    ELSE NULL
  END AS LSR_Escalated,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
    THEN CASE WHEN jira_esc.Jira_Key IS NULL THEN 'PASS' ELSE 'FAIL' END
    ELSE NULL
  END AS LSR_PassFail,

  CASE
    WHEN base.CaseType = 'Incident'
     AND base.Status IN ('Resolved', 'Closed')
    THEN base.Incident_Number
    ELSE NULL
  END AS LSR_InScope,

  CASE
    WHEN worklog_details.Incident_Number IS NOT NULL THEN base.Incident_Number ELSE NULL
  END AS Transaction_Handled,

  CASE
    WHEN base.CaseType = 'Incident' AND base.Status IN ('Resolved', 'Closed') THEN base.Incident_Number ELSE NULL
  END AS Closed_Tickets,

  CASE
    WHEN base.Assignee IS NOT NULL THEN base.Incident_Number ELSE NULL
  END AS Transaction_Assigned,

  CASE
    WHEN base.CaseType = 'Incident' AND base.Status IN ('Resolved', 'Closed')
    THEN ROUND(
      (
        CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND base.GCSC_1st_Customer_Update IS NOT NULL
           AND base.Submit_Date IS NOT NULL
           AND TIMESTAMP_DIFF(base.GCSC_1st_Customer_Update, base.Submit_Date, MINUTE) <= 30
          THEN 8 ELSE 0 END
        + CASE
          WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0
           AND base.`2nd_Response_PassFail` = 'PASS'
          THEN 7 ELSE 0 END
        + CASE
          WHEN base.Priority IN ('Critical', 'High')
           AND base.Normalized_Fault_Cause IN (SELECT cause FROM mttr_allowed_fault_causes)
           AND base.TrueMTTR_mins <= 90
          THEN 15 ELSE 0 END
        + CASE WHEN jira_esc.Jira_Key IS NULL THEN 10 ELSE 0 END
      ) /
      (
        CASE WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0 THEN 8 ELSE 0 END
        + CASE WHEN COALESCE(email_wl.EmailProgressUpdate_Count, 0) > 0 THEN 7 ELSE 0 END
        + CASE
          WHEN base.Priority IN ('Critical', 'High')
           AND base.Normalized_Fault_Cause IN (SELECT cause FROM mttr_allowed_fault_causes)
          THEN 15 ELSE 0 END
        + 10
      ) * 100,
      2
    )
    ELSE NULL
  END AS KPI_CompositeScore,

  base.CaseType,
  base.Status,
  base.TicketProcess,
  base.Priority,
  base.Urgency,
  base.Categorization_Tier_1,
  base.Categorization_Tier_2,
  base.Categorization_Tier_3,
  base.Fault_Cause,
  base.AIFaultCause

FROM base
LEFT JOIN jira_esc
  ON jira_esc.Incident_Number = base.Incident_Number
LEFT JOIN email_wl
  ON email_wl.Incident_Number = base.Incident_Number
LEFT JOIN worklog_details
  ON worklog_details.Incident_Number = base.Incident_Number