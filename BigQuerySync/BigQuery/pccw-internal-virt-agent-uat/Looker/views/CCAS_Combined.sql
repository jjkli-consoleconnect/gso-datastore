WITH TicketWithLinkedKeys AS (
  SELECT
    t.*,
    (
      SELECT STRING_AGG(key)
      FROM (
        SELECT JSON_VALUE(link, '$.inwardIssue.key') AS key
        FROM UNNEST(JSON_QUERY_ARRAY(t.Links, '$')) AS link
        WHERE JSON_VALUE(link, '$.inwardIssue.key') IS NOT NULL
        UNION ALL
        SELECT JSON_VALUE(link, '$.outwardIssue.key') AS key
        FROM UNNEST(JSON_QUERY_ARRAY(t.Links, '$')) AS link
        WHERE JSON_VALUE(link, '$.outwardIssue.key') IS NOT NULL
      )
    ) AS linkedkeys
  FROM
    `pccw-internal-virt-agent-uat.GSO.JiraTickets` t
  WHERE REGEXP_CONTAINS(COALESCE(t.Key, ''), r'(CCAS)')
)

SELECT
  twk.Key AS Issue_Key,
  twk.T AS Type,
  twk.Summary,
  twk.Status,
  twk.Priority,
  twk.Assignee,
  twk.Created AS Ticket_Created,
  twk.Updated AS Ticket_Updated,
  twk.Resolved AS Ticket_Resolved,
  twk.linkedkeys,
  twk.AppSupEscalation,
  twk.Resolution,

  -- Resolution SLA calculation (in hours)
  TIMESTAMP_DIFF(twk.Resolved, twk.Created, HOUR) AS Resolution_hrs,
  TIMESTAMP_DIFF(twk.Resolved, twk.Created, DAY) AS Resolution_days,

  -- SLA target (example: 24h for most, 8h for Incident, 1d for Service Request)
  CASE
    WHEN twk.T = 'Incident' THEN 8
    WHEN twk.T = 'Service Request' THEN 24
    ELSE 24
  END AS SLA_Resolution_Target_hrs,

  -- SLA met/breached
  CASE
    WHEN twk.Resolved IS NULL THEN NULL
    WHEN TIMESTAMP_DIFF(twk.Resolved, twk.Created, MINUTE) / 60.0 <= 
         CASE WHEN twk.T = 'Incident' THEN 8
              WHEN twk.T = 'Service Request' THEN 24
              ELSE 24 END
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
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bCCSUP(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCSUPSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bSLSUP(-\d+)?\b') THEN twk.Key ELSE NULL END AS SLSUPSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bCCONB(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCONBSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bCOPS(-\d+)?\b') THEN twk.Key ELSE NULL END AS COPSSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bCSCM(-\d+)?\b') THEN twk.Key ELSE NULL END AS CSCMSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bTAC(-\d+)?\b') THEN twk.Key ELSE NULL END AS TACSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bCCT4(-\d+)?\b') THEN twk.Key ELSE NULL END AS CCT4Solved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bSH(-\d+)?\b') THEN twk.Key ELSE NULL END AS SHSolved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bAS3491(-\d+)?\b') THEN twk.Key ELSE NULL END AS AS3491Solved,
  CASE WHEN REGEXP_CONTAINS(twk.linkedkeys, r'\bTCM(-\d+)?\b') THEN twk.Key ELSE NULL END AS TCMSolved,

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
  TicketWithLinkedKeys twk
LEFT JOIN
  `pccw-internal-virt-agent-uat.JIRAProjects.CCAS_comments` c
ON
  twk.Key = c.Issue_Key
LEFT JOIN
  `pccw-internal-virt-agent-uat.JIRAProjects.CCAS_changelog` l
ON
  twk.Key = l.Issue_Key
