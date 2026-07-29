UPDATE `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS T
SET RSMName = CASE
  WHEN ARRAY_LENGTH(
    ARRAY(
      SELECT TRIM(part)
      FROM UNNEST(SPLIT(TRIM(T.RSMName, '"'), ',')) AS part
      WHERE TRIM(part) != ''
    )
  ) >= 2 THEN ARRAY_TO_STRING(
    ARRAY_CONCAT(
      ARRAY(
        SELECT part
        FROM UNNEST(
          ARRAY(
            SELECT TRIM(part)
            FROM UNNEST(SPLIT(TRIM(T.RSMName, '"'), ',')) AS part
            WHERE TRIM(part) != ''
          )
        ) AS part WITH OFFSET pos
        WHERE pos > 0
        ORDER BY pos
      ),
      [
        ARRAY(
          SELECT TRIM(part)
          FROM UNNEST(SPLIT(TRIM(T.RSMName, '"'), ',')) AS part
          WHERE TRIM(part) != ''
        )[OFFSET(0)]
      ]
    ),
    ' '
  )
  ELSE TRIM(T.RSMName, '"')
END
WHERE T.RSMName IS NOT NULL
  AND TRIM(CAST(T.RSMName AS STRING)) != ''
  AND STRPOS(T.RSMName, ',') > 0;
