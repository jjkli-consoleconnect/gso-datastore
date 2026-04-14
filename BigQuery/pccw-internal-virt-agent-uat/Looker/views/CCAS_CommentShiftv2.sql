WITH parsed_links AS (
  SELECT 
    *,
    (
      SELECT STRING_AGG(
        COALESCE(
          JSON_EXTRACT_SCALAR(link, '$.outwardIssue.key'), 
          JSON_EXTRACT_SCALAR(link, '$.inwardIssue.key')
        ), ',')
      FROM UNNEST(JSON_EXTRACT_ARRAY(Links, '$')) AS link
    ) AS linkedkeys
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCAS`
),
name_filter AS (
  SELECT name FROM UNNEST([
    'Bautista Kevin Bryan',
    'Carl Jeffrey De Guzman',
    'Carpio Mae Rejoice',
    'De Guzman Carl Jeffrey',
    'Esguerra Fregie',
    'Evangelista John Darell',
    'Fregie Esguerra',
    'Garcia Marvic',
    'John Darell Evangelista',
    'Liza Necio',
    'Lloyd Stoltz',
    'Ma Lourdes Robledo',
    'Mae Rejoice Carpio',
    'Marvic Garcia',
    'Mary Grace Ydel',
    'Necio Liza Fernandez',
    'Nelson Irvin Realizo',
    'Paclibar Zacarias',
    'Realizo Nelson Irvin',
    'Robledo Ma Lourdes',
    'Stoltz Lloyd',
    'Ydel Mary Grace',
    'Zacarias Paclibar'
  ]) AS name
)

SELECT *
FROM (
  SELECT
    -- Created
    p.`Key`,
    p.Created AS Timestamp,
    p.Creator AS User_FullName,
    NULL AS Comment_ID,
    p.Type,
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
    p.`Key`,
    p.Resolved AS Timestamp,
    p.Assignee AS User_FullName,
    NULL AS Comment_ID,
    p.Type,
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
    c.Issue_Key AS `Key`,
    c.Updated AS Timestamp,
    c.Author_Display_Name AS User_FullName,
    c.Comment_ID,
    p.Type,
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
  FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCAS_comments` c
  LEFT JOIN parsed_links p ON c.Issue_Key = p.`Key`
)
WHERE User_FullName IN (SELECT name FROM name_filter)
