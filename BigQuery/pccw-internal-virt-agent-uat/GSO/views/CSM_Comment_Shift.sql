WITH parsed_links AS (
  SELECT 
    *,
    (
      SELECT STRING_AGG(
        COALESCE(
          JSON_EXTRACT_SCALAR(links, '$.outwardIssue.key'), 
          JSON_EXTRACT_SCALAR(links, '$.inwardIssue.key')
        ), ',')
      FROM UNNEST(JSON_EXTRACT_ARRAY(Links_Clean, '$')) AS links
    ) AS linkedkeys
  FROM `pccw-internal-virt-agent-uat.GSO.CSM`
),
name_filter AS (
  SELECT name FROM UNNEST([
    'Carpio Mae Rejoice',
    'Mae Rejoice Carpio',
    'Liza Necio',
    'Necio Liza Fernandez',
    'Ma Lourdes Robledo',
    'Robledo Ma Lourdes',
    'Mary Grace Ydel',
    'Ydel Mary Grace'
  ]) AS name
)

SELECT *
FROM (
  SELECT
    -- Created
    p.Ticket_Key,
    p.Created AS Timestamp,
    p.Assignee AS User_FullName,
    `Comments`[SAFE_OFFSET(0)].Comment_ID AS Comment_ID,
    p.T AS Type,
    CASE
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Created) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Created) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Created) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM p.Created) = 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(p.Created, INTERVAL 1 DAY)) || ' - 1 Morning'
      ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(p.Created, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS Shift,
    CASE
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', p.Created)
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', p.Created)
      WHEN EXTRACT(HOUR FROM p.Created) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', p.Created)
      WHEN EXTRACT(HOUR FROM p.Created) = 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(p.Created, INTERVAL 1 DAY))
      ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(p.Created, INTERVAL 1 DAY))
    END AS DoW,
    'Created' AS ActionType
  FROM parsed_links p

  UNION ALL

  SELECT
    -- Resolved
    p.Ticket_Key,
    p.Resolved AS Timestamp,
    p.Assignee AS User_FullName,
    `Comments`[SAFE_OFFSET(0)].Comment_ID AS Comment_ID,
    p.T AS Type,
    CASE
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Resolved) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Resolved) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', p.Resolved) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM p.Resolved) = 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(p.Resolved, INTERVAL 1 DAY)) || ' - 1 Morning'
      ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(p.Resolved, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS Shift,
    CASE
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', p.Resolved)
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', p.Resolved)
      WHEN EXTRACT(HOUR FROM p.Resolved) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', p.Resolved)
      WHEN EXTRACT(HOUR FROM p.Resolved) = 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(p.Resolved, INTERVAL 1 DAY))
      ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(p.Resolved, INTERVAL 1 DAY))
    END AS DoW,
    'Resolved' AS ActionType
  FROM parsed_links p

  UNION ALL

  SELECT
    -- Commented
  c.Ticket_Key AS Ticket_Key,
  c.Updated AS Timestamp,
  cm.Author_Display_Name AS User_FullName,
  cm.Comment_ID AS Comment_ID,
  c.T AS Type,
    CASE
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Updated) || ' - 1 Morning'
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Updated) || ' - 2 Afternoon'
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', c.Updated) || ' - 3 Evening'
      WHEN EXTRACT(HOUR FROM c.Updated) = 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(c.Updated, INTERVAL 1 DAY)) || ' - 1 Morning'
      ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(c.Updated, INTERVAL 1 DAY)) || ' - 1 Morning'
    END AS Shift,
    CASE
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', c.Updated)
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', c.Updated)
      WHEN EXTRACT(HOUR FROM c.Updated) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', c.Updated)
      WHEN EXTRACT(HOUR FROM c.Updated) = 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(c.Updated, INTERVAL 1 DAY))
      ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(c.Updated, INTERVAL 1 DAY))
    END AS DoW,
    'Commented' AS ActionType
  FROM parsed_links c
  CROSS JOIN UNNEST(c.Comments) AS cm
)
WHERE User_FullName IN (SELECT name FROM name_filter)
