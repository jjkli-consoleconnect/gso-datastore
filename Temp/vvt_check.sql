SELECT
  COUNT(*) AS status_rows_with_null_to,
  COUNT(DISTINCT Issue_Key) AS tickets_affected
FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog`
WHERE COALESCE(Issue_Key, '') LIKE 'VVT-%'
  AND LOWER(COALESCE(Changed_Field, '')) = 'status'
  AND Transitioned_To IS NULL;
