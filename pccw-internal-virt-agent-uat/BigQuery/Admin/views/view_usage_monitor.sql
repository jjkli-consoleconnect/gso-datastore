WITH view_objects AS (
  SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.Admin.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.BMC.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.BMCQA.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.CostItemExpiration.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.JIRAProjects.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.Looker.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.QMS.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.RemedyICS.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.Snapshot.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.Staging.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.SubCableEvents.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.Testing.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.sheldon_testing.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.wanda_billing.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
  UNION ALL SELECT table_catalog, table_schema, table_name FROM `pccw-internal-virt-agent-uat.wanda_ds.INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW'
),
jobs AS (
  SELECT job_id, user_email, creation_time, query, referenced_tables
  FROM `region-eu`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
  WHERE project_id = 'pccw-internal-virt-agent-uat'
    AND job_type = 'QUERY'
    AND state = 'DONE'
    AND error_result IS NULL
    AND statement_type = 'SELECT'
),
refs_from_referenced_tables AS (
  SELECT DISTINCT
    j.job_id, j.user_email, j.creation_time,
    r.project_id, r.dataset_id, r.table_id
  FROM jobs j
  CROSS JOIN UNNEST(IFNULL(j.referenced_tables, [])) AS r
  WHERE r.project_id = 'pccw-internal-virt-agent-uat'
),
refs_from_query_text AS (
  SELECT DISTINCT
    j.job_id, j.user_email, j.creation_time,
    SPLIT(ref, '.')[OFFSET(0)] AS project_id,
    SPLIT(ref, '.')[OFFSET(1)] AS dataset_id,
    SPLIT(ref, '.')[OFFSET(2)] AS table_id
  FROM jobs j
  CROSS JOIN UNNEST(REGEXP_EXTRACT_ALL(IFNULL(j.query, ''), r'`([^`]*)`')) AS ref
  WHERE ARRAY_LENGTH(SPLIT(ref, '.')) = 3
    AND SPLIT(ref, '.')[OFFSET(0)] = 'pccw-internal-virt-agent-uat'
),
all_refs AS (
  SELECT * FROM refs_from_referenced_tables
  UNION DISTINCT
  SELECT * FROM refs_from_query_text
)
SELECT
  DATE(a.creation_time) AS query_date,
  a.project_id,
  a.dataset_id AS object_dataset,
  a.table_id AS object_name,
  a.user_email AS queried_by,
  COUNT(*) AS query_count,
  MIN(a.creation_time) AS first_queried_at,
  MAX(a.creation_time) AS last_queried_at
FROM all_refs a
JOIN view_objects vo
  ON vo.table_catalog = a.project_id
 AND vo.table_schema = a.dataset_id
 AND vo.table_name = a.table_id
GROUP BY 1, 2, 3, 4, 5
