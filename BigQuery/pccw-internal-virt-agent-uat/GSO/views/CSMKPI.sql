-- CSMKPI
-- Ticket-level KPI view for the CSM (Jira) project, modeled on GSO.Tier1KPI (Remedy).
-- Source of truth: GSO.CSM (JiraTickets filtered to Project = 'CSM') + its comment array.
--
-- Logic parallels Tier1KPI, but fields remain Jira-native:
--   Ticket_Key / Project / Reporter / Assignee / Resolved / Comments / Changelogs
--   LSR logic is Jira-specific: link to a non-CSM ticket (LinkedProject_Clean)
--
-- Assumptions / deviations from Tier1KPI (documented, per business decision):
--   * MTTR "in scope" is ALL Resolved/Closed CSM tickets. The Remedy gate
--     (Priority Critical/High + fault-cause whitelist) is DROPPED because the CSM
--     Jira data exposes no Priority or Fault_Cause field.
--   * Sanity thresholds kept identical to Remedy: FRT pass <= 30 min, SRT pass
--     <= 90 min, MTTR pass <= 90 min.
--   * "Customer-facing response" in Jira is approximated by comments from the
--     CSM responder roster below. FRT uses the first qualifying responder comment;
--     SRT uses the second qualifying responder comment.

WITH responder_roster AS (
  SELECT 'Liza Necio' AS Responder_Name UNION ALL
  SELECT 'Ma Lourdes Robledo' UNION ALL
  SELECT 'Mae Rejoice Carpio' UNION ALL
  SELECT 'Mary Grace Ydel'
),

base AS (
  SELECT
    c.Ticket_Key,
    c.T AS Issue_Type,
    c.Status,
    c.Created,
    c.Updated,
    c.Resolved,
    c.Reporter AS Submitter,
    c.Assignee,
    c.Project AS Assigned_Group,
    ARRAY_TO_STRING(COALESCE(c.Component, []), ', ') AS Component_Joined,
    c.Summary,
    c.LinkedProject_Clean,
    ARRAY_TO_STRING(c.RemedyTicketNumber, ', ') AS RemedyTicketNumber_Joined,
    c.SR_Ref,
    (
      SELECT ch.Transitioned_By_Display_Name
      FROM UNNEST(c.Changelogs) AS ch
      WHERE UPPER(COALESCE(ch.Transitioned_To, '')) IN ('RESOLVED', 'CLOSED')
        AND ch.Transitioned_By_Display_Name IS NOT NULL
      ORDER BY ch.Transition_Timestamp DESC
      LIMIT 1
    ) AS Resolved_By,
    ARRAY(
      SELECT cs.Created
      FROM UNNEST(c.Comments) AS cs
      JOIN responder_roster rr
        ON TRIM(COALESCE(cs.Author_Display_Name, '')) = rr.Responder_Name
      WHERE cs.Created IS NOT NULL
      ORDER BY cs.Created, cs.Comment_ID
    ) AS Responder_Comment_Times,
    ARRAY(
      SELECT AS STRUCT
        cs.Comment_ID,
        cs.Author_Account_ID,
        cs.Author_Display_Name,
        cs.Created,
        cs.Updated,
        cs.Body,
        ROW_NUMBER() OVER (ORDER BY cs.Created, cs.Comment_ID) AS Comment_Sequence
      FROM UNNEST(c.Comments) AS cs
      JOIN responder_roster rr
        ON TRIM(COALESCE(cs.Author_Display_Name, '')) = rr.Responder_Name
      WHERE cs.Created IS NOT NULL
    ) AS Comment_Details,
    c.Comments AS Comments,
    c.Changelogs AS Changelogs
  FROM `pccw-internal-virt-agent-uat.GSO.CSM` c
),
edge AS (
  SELECT
    b.*,
    Responder_Comment_Times[SAFE_OFFSET(0)] AS First_Comment_At,
    Responder_Comment_Times[SAFE_OFFSET(1)] AS Second_Comment_At,
    (
      SELECT cd.Author_Display_Name
      FROM UNNEST(b.Comment_Details) AS cd
      WHERE cd.Comment_Sequence = 1
      LIMIT 1
    ) AS First_Comment_By,
    (
      SELECT cd.Author_Display_Name
      FROM UNNEST(b.Comment_Details) AS cd
      WHERE cd.Comment_Sequence = 2
      LIMIT 1
    ) AS Second_Comment_By,
    ARRAY_LENGTH(Responder_Comment_Times) AS Comment_Count,
    -- LSR: FAIL if the ticket is linked to any non-CSM project (LinkedProject_Clean
    -- already excludes the ticket's own/self project, so any element = external link)
    (ARRAY_LENGTH(LinkedProject_Clean) > 0) AS Is_Escalated
  FROM base b
)
SELECT
  -- Ticket identity / attributes
  Ticket_Key,
  Assigned_Group,
  Assignee,
  Submitter,
  Submitter AS Ticket_Submitter,
  Resolved_By,
  Comment_Details,
  Issue_Type AS CaseType,
  Status,
  Created,
  Resolved,
  Comment_Count,
  First_Comment_At,
  First_Comment_By,
  Second_Comment_At,
  Second_Comment_By,
  Component_Joined,
  RemedyTicketNumber_Joined,
  SR_Ref,
  Comments,
  Changelogs,


  -- ===== FRT (First Response Time): Created -> first comment =====
  CASE
    WHEN Comment_Count >= 1 AND Status IN ('Resolved', 'Closed') AND First_Comment_At IS NOT NULL
    THEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE)
    ELSE NULL
  END AS FRT_Minutes,
  CASE
    WHEN Comment_Count >= 1 AND Status IN ('Resolved', 'Closed') AND First_Comment_At IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) <= 30 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE NULL
  END AS FRT_PassFail,
  CASE
    WHEN Comment_Count >= 1 AND Status IN ('Resolved', 'Closed') AND First_Comment_At IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 15 THEN 7
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 30 THEN 6
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 45 THEN 5
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 60 THEN 4
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 75 THEN 3
      WHEN TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) < 90 THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS FRT_Rating,
  CASE
    WHEN Comment_Count >= 1 AND Status IN ('Resolved', 'Closed') THEN 1 ELSE NULL
  END AS FRT_InScope,

  -- ===== SRT (Second Response Time): first comment -> second comment =====
  CASE
    WHEN Comment_Count >= 2 AND Status IN ('Resolved', 'Closed')
    THEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE)
    ELSE NULL
  END AS SRT_Minutes,
  CASE
    WHEN Comment_Count >= 2 AND Status IN ('Resolved', 'Closed')
    THEN CASE
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE NULL
  END AS SRT_PassFail,
  CASE
    WHEN Comment_Count >= 2 AND Status IN ('Resolved', 'Closed')
    THEN CASE
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 45 THEN 7
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 60 THEN 6
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 75 THEN 5
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 90 THEN 4
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 105 THEN 3
      WHEN TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) < 150 THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS SRT_Rating,
  CASE
    WHEN Comment_Count >= 2 AND Status IN ('Resolved', 'Closed') THEN 1 ELSE NULL
  END AS SRT_InScope,

  -- ===== MTTR (Time to resolve): Created -> Resolved =====
  -- NOTE: Remedy's Critical/High + fault-cause gate intentionally dropped (see header).
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Resolved IS NOT NULL
    THEN TIMESTAMP_DIFF(Resolved, Created, MINUTE)
    ELSE NULL
  END AS MTTR_Minutes,
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Resolved IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) <= 90 THEN 'PASS'
      ELSE 'FAIL'
    END
    ELSE NULL
  END AS MTTR_PassFail,
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Resolved IS NOT NULL THEN 1 ELSE NULL
  END AS MTTR_InScope,
  -- MTTR Rating: 7-point scale on time-to-resolve minutes (same bands as Tier1KPI)
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Resolved IS NOT NULL
    THEN CASE
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 45 THEN 7
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 60 THEN 6
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 75 THEN 5
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 90 THEN 4
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 105 THEN 3
      WHEN TIMESTAMP_DIFF(Resolved, Created, MINUTE) < 150 THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS MTTR_Rating,

  -- ===== LSR (escalation control): PASS when no link to a non-CSM ticket =====
  CASE
    WHEN Status IN ('Resolved', 'Closed')
    THEN CASE WHEN Is_Escalated THEN 'FAIL' ELSE 'PASS' END
    ELSE NULL
  END AS LSR_PassFail,
  -- LSR_Escalated: ticket key when escalated (mirrors Tier1KPI.LSR_Escalated)
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Is_Escalated THEN Ticket_Key ELSE NULL
  END AS LSR_Escalated,
  CASE
    WHEN Status IN ('Resolved', 'Closed') THEN 1 ELSE NULL
  END AS LSR_InScope,

  -- ===== Transaction / volume fields =====
  CASE WHEN ARRAY_LENGTH(Comment_Details) > 0 THEN Ticket_Key ELSE NULL END AS Transaction_Handled,
  CASE WHEN Status IN ('Resolved', 'Closed') THEN Ticket_Key ELSE NULL END AS Closed_Tickets,
  CASE WHEN Assignee IS NOT NULL THEN Ticket_Key ELSE NULL END AS Transaction_Assigned,
  CASE WHEN Status IN ('Resolved', 'Closed') THEN 1 ELSE NULL END AS ClosedTickets_InScope,
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Assignee IS NOT NULL AND TRIM(Assignee) != ''
    THEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
      PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
    )
    ELSE NULL
  END AS Closed_Tickets_Monthly_Count,
  -- CSM-calibrated bands from full project history (assignee-month distribution, 2023-06..2026-08):
  -- p50=5, p65=8, p80=14, p90=22, max=56
  CASE
    WHEN Status IN ('Resolved', 'Closed') AND Assignee IS NOT NULL AND TRIM(Assignee) != ''
    THEN CASE
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 22 THEN 7
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 14 THEN 6
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 8 THEN 5
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 5 THEN 4
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 3 THEN 3
      WHEN COUNTIF(Status IN ('Resolved', 'Closed')) OVER (
        PARTITION BY Assignee, DATE_TRUNC(DATE(Resolved), MONTH)
      ) >= 2 THEN 2
      ELSE 1
    END
    ELSE NULL
  END AS Closed_Tickets_Rating,

  -- ===== Person fields for Tier1-like visualization on Jira-native data =====
  COALESCE(NULLIF(Assignee, ''), NULLIF(Resolved_By, ''), NULLIF(Submitter, '')) AS Person_Name,
  CASE
    WHEN Comment_Count >= 1 AND First_Comment_By IS NOT NULL THEN First_Comment_By
    ELSE NULL
  END AS First_Response_By,
  CASE
    WHEN Comment_Count >= 2 AND Second_Comment_By IS NOT NULL THEN Second_Comment_By
    ELSE NULL
  END AS Second_Response_By,

  -- ===== KPI Composite Score (weighted %, mirrors Tier1KPI) =====
  -- FRT 8 + SRT 7 + MTTR 15 + LSR 10 = 40 achievable points.
  -- Denominator drops components the ticket is not eligible for.
  CASE
    WHEN Status IN ('Resolved', 'Closed')
    THEN ROUND(
      (
        CASE WHEN Comment_Count >= 1 AND First_Comment_At IS NOT NULL
              AND TIMESTAMP_DIFF(First_Comment_At, Created, MINUTE) <= 30 THEN 8 ELSE 0 END
        + CASE WHEN Comment_Count >= 2
                AND TIMESTAMP_DIFF(Second_Comment_At, First_Comment_At, MINUTE) <= 90 THEN 7 ELSE 0 END
        + CASE WHEN Resolved IS NOT NULL
                AND TIMESTAMP_DIFF(Resolved, Created, MINUTE) <= 90 THEN 15 ELSE 0 END
        + CASE WHEN NOT Is_Escalated THEN 10 ELSE 0 END
      ) / (
        CASE WHEN Comment_Count >= 1 THEN 8 ELSE 0 END
        + CASE WHEN Comment_Count >= 2 THEN 7 ELSE 0 END
        + CASE WHEN Resolved IS NOT NULL THEN 15 ELSE 0 END
        + 10
      ) * 100,
      2
    )
    ELSE NULL
  END AS KPI_CompositeScore

FROM edge
WHERE Assigned_Group = 'CSM'
