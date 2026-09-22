WITH raw_logs AS (
  SELECT 'PROJ-1' AS issue_key, '2026-06-01 10:00' AS ts, 'Open' AS status_from, 'In Progress' AS status_to UNION ALL
  SELECT 'PROJ-1', '2026-06-02 14:00', 'In Progress', 'Done'
)
SELECT
  issue_key,
  -- STRUCT bundles multiple columns, ARRAY_AGG keeps them ordered in an array
  STRUCT(ts, status_from, status_to) AS changelog_struct
FROM raw_logs


