WITH sample AS (
  SELECT
    Incident_Number,
    RSMName AS original_rsmname,
    TRIM(RSMName, '"') AS trimmed_rsmname,
    ARRAY(
      SELECT TRIM(part)
      FROM UNNEST(SPLIT(TRIM(RSMName, '"'), ',')) AS part
      WHERE TRIM(part) != ''
    ) AS parts
  FROM `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC`
  WHERE RSMName IS NOT NULL
    AND TRIM(CAST(RSMName AS STRING)) != ''
    AND STRPOS(RSMName, ',') > 0
  LIMIT 10
)
SELECT
  Incident_Number,
  original_rsmname,
  ARRAY_TO_STRING(
    ARRAY_CONCAT(
      ARRAY(
        SELECT part
        FROM UNNEST(parts) AS part WITH OFFSET pos
        WHERE pos > 0
        ORDER BY pos
      ),
      [parts[OFFSET(0)]]
    ),
    ' '
  ) AS normalized_rsmname
FROM sample;
