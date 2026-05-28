WITH TicketWithLinkedKeys AS (
  SELECT
    t.*,
    (
      SELECT STRING_AGG(key)
      FROM (
        SELECT JSON_VALUE(Links, '$.inwardIssue.key') AS key
        FROM UNNEST(JSON_QUERY_ARRAY(t.Links, '$')) AS Links
        WHERE JSON_VALUE(Links, '$.inwardIssue.key') IS NOT NULL
        UNION ALL
        SELECT JSON_VALUE(Links, '$.outwardIssue.key') AS key
        FROM UNNEST(JSON_QUERY_ARRAY(t.Links, '$')) AS Links
        WHERE JSON_VALUE(Links, '$.outwardIssue.key') IS NOT NULL
      )
    ) AS linkedkeys
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
  WHERE REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAS)')
),
StatusTransitions AS (
  SELECT
    l.Issue_Key,
    l.Transitioned_To AS status,
    l.Transition_Timestamp AS status_start,
    LEAD(l.Transition_Timestamp) OVER (
      PARTITION BY l.Issue_Key
      ORDER BY l.Transition_Timestamp
    ) AS status_end
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraChangelog` l
  WHERE l.Issue_Key IN (SELECT Key FROM TicketWithLinkedKeys)
),
FirstTriagingOrReviewing AS (
  SELECT
    Issue_Key,
    MIN(status_start) AS first_ack_timestamp
  FROM
    StatusTransitions
  WHERE status IN ('Triaging', 'Reviewing')
  GROUP BY
    Issue_Key
),
FirstClosed AS (
  SELECT
    Issue_Key,
    MIN(status_start) AS first_closed_timestamp
  FROM
    StatusTransitions
  WHERE status = 'Closed'
  GROUP BY
    Issue_Key
),
MTTRDurations AS (
  SELECT
    Issue_Key,
    -- MTTR (SLA): Sum of time in active statuses
    SUM(
      CASE
        WHEN status IN ('In Progress', 'Triaging', 'Reviewing', 'Escalated') THEN
          TIMESTAMP_DIFF(
            COALESCE(status_end, CURRENT_TIMESTAMP()),
            status_start,
            SECOND
          )
        ELSE 0
      END
    ) AS mttr_sla_seconds,
    -- MTTR (Hold): Sum of time in hold statuses (anything with Pending, plus Acknowledge, Blocked, RPO Coordination)
    SUM(
      CASE
        WHEN status LIKE '%Pending%' 
          OR status IN ('Acknowledge', 'Blocked', 'RPO Coordination') THEN
          TIMESTAMP_DIFF(
            COALESCE(status_end, CURRENT_TIMESTAMP()),
            status_start,
            SECOND
          )
        ELSE 0
      END
    ) AS mttr_hold_seconds
  FROM
    StatusTransitions
  GROUP BY
    Issue_Key
),
TicketWithSla AS (
  SELECT
    twk.*,
    ftr.first_ack_timestamp,
    fc.first_closed_timestamp,
    mttr.mttr_sla_seconds,
    mttr.mttr_hold_seconds
  FROM
    TicketWithLinkedKeys twk
  LEFT JOIN
    FirstTriagingOrReviewing ftr
  ON twk.Key = ftr.Issue_Key
  LEFT JOIN
    FirstClosed fc
  ON twk.Key = fc.Issue_Key
  LEFT JOIN
    MTTRDurations mttr
  ON twk.Key = mttr.Issue_Key
),
TimeMetrics AS (
  SELECT
    tws.* EXCEPT(mttr_sla_seconds, mttr_hold_seconds),
    
    -- MTTA: Mean Time to Acknowledge (seconds from creation to first Triaging/Reviewing)
    CASE
      WHEN tws.first_ack_timestamp IS NULL THEN NULL
      ELSE TIMESTAMP_DIFF(tws.first_ack_timestamp, tws.Created, SECOND)
    END AS mtta_seconds,
    
    -- MTTR (SLA): Sum of active status time
    COALESCE(tws.mttr_sla_seconds, 0) AS mttr_sla_seconds,
    
    -- MTTR (Hold): Sum of hold status time
    COALESCE(tws.mttr_hold_seconds, 0) AS mttr_hold_seconds,
    
    -- MTTC: Mean Time to Close (seconds from creation to first Closed status)
    CASE
      WHEN tws.first_closed_timestamp IS NULL THEN NULL
      ELSE TIMESTAMP_DIFF(tws.first_closed_timestamp, tws.Created, SECOND)
    END AS mttc_seconds,

    -- SLA grouping based on documented work-type scope
    CASE
      WHEN tws.T IN ('Application Problem', 'Application Incident', 'Proactive Alert') THEN 'Incident'
      WHEN tws.T IN (
        'Support Request',
        'Customer Change Request',
        'Platform Change Request',
        'Migration Request',
        'Device/Port Onboard',
        'Cloud NNI Turn Up'
      ) THEN 'Service Request'
      ELSE 'Other'
    END AS SLA_Work_Type,

    -- MTTA target by work-type and priority
    CASE
      WHEN tws.T IN ('Application Problem', 'Application Incident', 'Proactive Alert') THEN
        CASE
          WHEN tws.Priority IN ('Blocker', 'Critical', 'Highest') THEN 0
          WHEN tws.Priority = 'High' THEN 1200
          WHEN tws.Priority IN ('Medium', 'Normal') THEN 7200
          WHEN tws.Priority IN ('Low', 'Minor') THEN 259200
          ELSE NULL
        END
      WHEN tws.T IN (
        'Support Request',
        'Customer Change Request',
        'Platform Change Request',
        'Migration Request',
        'Device/Port Onboard',
        'Cloud NNI Turn Up'
      ) THEN
        CASE
          WHEN tws.Priority IN ('Blocker', 'Critical', 'Highest') THEN 0
          WHEN tws.Priority = 'High' THEN 3600
          WHEN tws.Priority IN ('Medium', 'Normal') THEN 7200
          WHEN tws.Priority IN ('Low', 'Minor') THEN 14400
          ELSE NULL
        END
      ELSE NULL
    END AS mtta_target_seconds,

    -- MTTR target by priority for SLA-enabled work types
    CASE
      WHEN tws.T IN ('Platform Improvement', 'Sustaining Reliability Engineering', 'Task') THEN NULL
      WHEN tws.Priority IN ('Blocker', 'Critical', 'Highest') THEN 14400
      WHEN tws.Priority = 'High' THEN 28800
      WHEN tws.Priority IN ('Medium', 'Normal') THEN 57600
      WHEN tws.Priority IN ('Low', 'Minor') THEN 172800
      ELSE NULL
    END AS mttr_target_seconds
  FROM
    TicketWithSla tws
)

SELECT
  twk.Key AS Issue_Key,
  CASE
    WHEN twk.T = 'Application Incident' THEN 'Incident'
    WHEN twk.T = 'Application Problem' THEN 'Problem'
    ELSE twk.T
  END AS Type,
  twk.Summary,
  twk.Status,
  twk.Priority,
  twk.Assignee,
  twk.Created AS Ticket_Created,
  twk.Updated AS Ticket_Updated,
  twk.Resolved AS Ticket_Resolved,
  twk.first_closed_timestamp AS Ticket_Closed,
  twk.linkedkeys,
  twk.AppSupEscalation,
  twk.Resolution,
  twk.SyncTime,

  -- MTTA: Mean Time to Acknowledge (first response to Triaging/Reviewing)
  CASE
    WHEN twk.mtta_seconds IS NULL THEN NULL
    ELSE twk.mtta_seconds
  END AS MTTA_seconds,
  CASE
    WHEN twk.mtta_seconds IS NULL THEN NULL
    ELSE twk.mtta_seconds / 60.0
  END AS MTTA_minutes,
  CASE
    WHEN twk.mtta_seconds IS NULL THEN NULL
    ELSE twk.mtta_seconds / 3600.0
  END AS MTTA_hrs,
  CASE
    WHEN twk.mtta_seconds IS NULL THEN NULL
    ELSE twk.mtta_seconds / 86400.0
  END AS MTTA_days,

  -- MTTA SLA target and status
  CASE
    WHEN twk.mtta_target_seconds IS NULL THEN 'No Data'
    ELSE CAST(twk.mtta_target_seconds AS STRING)
  END AS SLA_MTTA_Target_seconds,
  CASE
    WHEN twk.mtta_target_seconds IS NULL THEN 'No Data'
    ELSE CAST(twk.mtta_target_seconds / 60.0 AS STRING)
  END AS SLA_MTTA_Target_minutes,
  CASE
    WHEN twk.mtta_target_seconds IS NULL OR twk.mtta_seconds IS NULL THEN 'No Data'
    WHEN twk.mtta_seconds <= twk.mtta_target_seconds THEN 'Met'
    ELSE 'Breached'
  END AS SLA_MTTA_Status,

  -- MTTR (SLA): Mean Time to Resolve - Active status time
  CASE
    WHEN twk.mttr_sla_seconds = 0 THEN NULL
    ELSE twk.mttr_sla_seconds
  END AS MTTR_SLA_seconds,
  CASE
    WHEN twk.mttr_sla_seconds = 0 THEN NULL
    ELSE twk.mttr_sla_seconds / 60.0
  END AS MTTR_SLA_minutes,
  CASE
    WHEN twk.mttr_sla_seconds = 0 THEN NULL
    ELSE twk.mttr_sla_seconds / 3600.0
  END AS MTTR_SLA_hrs,
  CASE
    WHEN twk.mttr_sla_seconds = 0 THEN NULL
    ELSE twk.mttr_sla_seconds / 86400.0
  END AS MTTR_SLA_days,

  -- MTTR (Hold): Mean Time to Resolve - Hold status time
  CASE
    WHEN twk.mttr_hold_seconds = 0 THEN NULL
    ELSE twk.mttr_hold_seconds
  END AS MTTR_Hold_seconds,
  CASE
    WHEN twk.mttr_hold_seconds = 0 THEN NULL
    ELSE twk.mttr_hold_seconds / 60.0
  END AS MTTR_Hold_minutes,
  CASE
    WHEN twk.mttr_hold_seconds = 0 THEN NULL
    ELSE twk.mttr_hold_seconds / 3600.0
  END AS MTTR_Hold_hrs,
  CASE
    WHEN twk.mttr_hold_seconds = 0 THEN NULL
    ELSE twk.mttr_hold_seconds / 86400.0
  END AS MTTR_Hold_days,

  -- MTTC: Mean Time to Close (from creation to Closed status)
  CASE
    WHEN twk.mttc_seconds IS NULL THEN NULL
    ELSE twk.mttc_seconds
  END AS MTTC_seconds,
  CASE
    WHEN twk.mttc_seconds IS NULL THEN NULL
    ELSE twk.mttc_seconds / 60.0
  END AS MTTC_minutes,
  CASE
    WHEN twk.mttc_seconds IS NULL THEN NULL
    ELSE twk.mttc_seconds / 3600.0
  END AS MTTC_hrs,
  CASE
    WHEN twk.mttc_seconds IS NULL THEN NULL
    ELSE twk.mttc_seconds / 86400.0
  END AS MTTC_days,

  -- SLA scope
  twk.SLA_Work_Type,

  -- SLA target for MTTR
  COALESCE(
    CAST(twk.mttr_target_seconds / 3600.0 AS STRING),
    'No Data'
  ) AS SLA_Resolution_Target_hrs,
  COALESCE(CAST(twk.mttr_target_seconds AS STRING), 'No Data') AS SLA_Resolution_Target_seconds,

  -- SLA met/breached (based on MTTR_SLA time)
  CASE
    WHEN twk.mttr_sla_seconds = 0 OR twk.mttr_sla_seconds IS NULL THEN 'No Data'
    WHEN twk.mttr_target_seconds IS NULL THEN 'No Data'
    WHEN twk.mttr_sla_seconds <= twk.mttr_target_seconds
    THEN 'Met'
    ELSE 'Breached'
  END AS SLA_Resolution_Status,

  -- CCASSolved logic using linkedkeys
  CASE
    WHEN twk.Links IS NULL OR twk.Links = '' THEN twk.Key
    WHEN NOT REGEXP_CONTAINS(twk.Links, r'(CCSUP|SLSUP|CCONB|COPS|CSCM|CCT4|SH|AS3491)(-\d+)?') THEN twk.Key
    ELSE NULL
  END AS CCASSolved,

  -- Individual Solved fields using linkedkeys
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bCCSUP(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCSUPSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bSLSUP(-\d+)?\b') THEN twk.Key ELSE NULL END AS SLSUPSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bCCONB(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCONBSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bCOPS(-\d+)?\b') THEN twk.Key ELSE NULL END AS COPSSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bCSCM(-\d+)?\b') THEN twk.Key ELSE NULL END AS CSCMSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bTAC(-\d+)?\b') THEN twk.Key ELSE NULL END AS TACSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bCCT4(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCT4Solved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bSH(-\d+)?\b') THEN twk.Key ELSE NULL END AS SHSolved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bAS3491(-\d+)?\b') THEN twk.Key ELSE NULL END AS AS3491Solved,
  CASE WHEN REGEXP_CONTAINS(twk.Links, r'\bTCM(-\d+)?\b') THEN twk.Key ELSE NULL END AS TCMSolved,

  -- Comment Info
  c.Comment_ID,
  c.Author_Display_Name AS Comment_Author,
  c.Created AS Comment_Created,
  c.Updated AS Comment_Updated,
  c.Body AS Comment_Body,
  c.Visibility_Type,
  c.Visibility_Value,

  -- Comment Shift
  CASE
    WHEN EXTRACT(HOUR FROM c.Created) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Created) || ' - 1 Morning'
    WHEN EXTRACT(HOUR FROM c.Created) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Created) || ' - 2 Afternoon'
    WHEN EXTRACT(HOUR FROM c.Created) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Created) || ' - 3 Evening'
    WHEN EXTRACT(HOUR FROM c.Created) = 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(c.Created, INTERVAL 1 DAY)) || ' - 1 Morning'
    ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(c.Created, INTERVAL 1 DAY)) || ' - 1 Morning'
  END AS Comment_Shift,

  -- Status Change Info
  l.History_ID,
  l.Transition_Timestamp,
  l.Transitioned_From,
  l.Transitioned_To,
  l.Transitioned_By_Display_Name

FROM
  TimeMetrics twk
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.JiraComments` c
ON
  twk.Key = c.Issue_Key
LEFT JOIN
  `pccw-internal-virt-agent-uat.GSO.JiraChangelog` l
ON
  twk.Key = l.Issue_Key
WHERE
  c.Author_Display_Name IS NULL
  OR c.Author_Display_Name NOT IN (
    'Liza Necio',
    'Necio Liza Fernandez',
    'Mary Grace Ydel',
    'Ydel Mary Grace',
    'Fregie Esguerra',
    'Esguerra Fregie'
  )

