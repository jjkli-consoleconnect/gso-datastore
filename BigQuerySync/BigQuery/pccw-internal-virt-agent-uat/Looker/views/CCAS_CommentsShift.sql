SELECT
    `Key`,
    Timestamp,
    User_FullName,
    Team,
    Comment_ID,
    Type,
    Shift,
    DoW,
    ActionType
  FROM (
    SELECT
        `Key`,
        Created AS Timestamp,
        Creator_FullName AS User_FullName,
        Creator_Group AS Team,
        NULL AS Comment_ID,
        Type,
        CASE
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Created) || ' - 1 Morning'
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Created) || ' - 2 Afternoon'
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Created) || ' - 3 Evening'
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Created, INTERVAL 1 DAY)) || ' - 1 Morning'
         ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Created, INTERVAL 1 DAY)) || ' - 1 Morning'
       END AS Shift,
        CASE
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', Created)
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', Created)
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', Created)
         WHEN EXTRACT(HOUR FROM Created) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(Created, INTERVAL 1 DAY))
         ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(Created, INTERVAL 1 DAY))
       END AS DoW,
        'Created' AS ActionType
      FROM
        `pccw-internal-virt-agent-uat.Looker.CCAS_Comments`

    UNION ALL

    SELECT
        `Key`,
        Resolved AS Timestamp,
        Assignee_FullName AS User_FullName,
        Assignee_Group AS Team,
        NULL AS Comment_ID,
        Type,
        CASE
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Resolved) || ' - 1 Morning'
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Resolved) || ' - 2 Afternoon'
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Resolved) || ' - 3 Evening'
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Resolved, INTERVAL 1 DAY)) || ' - 1 Morning'
         ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Resolved, INTERVAL 1 DAY)) || ' - 1 Morning'
       END AS Shift,
        CASE
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', Resolved)
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', Resolved)
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', Resolved)
         WHEN EXTRACT(HOUR FROM Resolved) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(Resolved, INTERVAL 1 DAY))
         ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(Resolved, INTERVAL 1 DAY))
       END AS DoW,
        'Resolved' AS ActionType
      FROM
        `pccw-internal-virt-agent-uat.Looker.CCAS_Comments`

    UNION ALL

    SELECT
        `Key`,
        Comment_Updated AS Timestamp,
        Commenter AS User_FullName,
        Commenter_Group AS Team,
        Comment_ID,
        Type,
        CASE
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Comment_Updated) || ' - 1 Morning'
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Comment_Updated) || ' - 2 Afternoon'
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%Y-%m-%d', Comment_Updated) || ' - 3 Evening'
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Comment_Updated, INTERVAL 1 DAY)) || ' - 1 Morning'
         ELSE FORMAT_TIMESTAMP('%Y-%m-%d', DATE_ADD(Comment_Updated, INTERVAL 1 DAY)) || ' - 1 Morning'
       END AS Shift,
        CASE
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 0 AND 6 THEN FORMAT_TIMESTAMP('%a', Comment_Updated)
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 7 AND 14 THEN FORMAT_TIMESTAMP('%a', Comment_Updated)
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 15 AND 22 THEN FORMAT_TIMESTAMP('%a', Comment_Updated)
         WHEN EXTRACT(HOUR FROM Comment_Updated) BETWEEN 23 AND 23 THEN FORMAT_TIMESTAMP('%a', DATE_ADD(Comment_Updated, INTERVAL 1 DAY))
         ELSE FORMAT_TIMESTAMP('%a', DATE_ADD(Comment_Updated, INTERVAL 1 DAY))
       END AS DoW,
        'Commented' AS ActionType
      FROM
        `pccw-internal-virt-agent-uat.Looker.CCAS_Comments`
  );
