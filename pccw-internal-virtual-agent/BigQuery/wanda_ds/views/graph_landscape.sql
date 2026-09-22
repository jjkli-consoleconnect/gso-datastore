WITH RECURSIVE
object_meta AS (
  SELECT
    CONCAT(table_catalog, '.', table_schema, '.', table_name) AS fq_object,
    table_catalog,
    table_schema,
    table_name,
    table_type
  FROM `pccw-internal-virtual-agent.wanda_ds.INFORMATION_SCHEMA.TABLES`
  UNION ALL
  SELECT
    CONCAT(table_catalog, '.', table_schema, '.', table_name) AS fq_object,
    table_catalog,
    table_schema,
    table_name,
    table_type
  FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.TABLES`
),
view_defs AS (
  SELECT
    CONCAT('pccw-internal-virtual-agent.wanda_ds.', table_name) AS fq_view,
    view_definition
  FROM `pccw-internal-virtual-agent.wanda_ds.INFORMATION_SCHEMA.VIEWS`
  UNION ALL
  SELECT
    CONCAT('pccw-internal-virt-agent-uat.GSO.', table_name) AS fq_view,
    view_definition
  FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.VIEWS`
),
direct_deps AS (
  SELECT DISTINCT
    vd.fq_view,
    ref AS fq_ref
  FROM view_defs vd
  CROSS JOIN UNNEST(REGEXP_EXTRACT_ALL(vd.view_definition, r'`([^`]+)`')) AS ref
  WHERE ARRAY_LENGTH(SPLIT(ref, '.')) = 3
    AND ref != vd.fq_view
),
root_views AS (
  SELECT fq_object AS target_fq_view
  FROM object_meta
  WHERE table_catalog = 'pccw-internal-virtual-agent'
    AND table_schema = 'wanda_ds'
    AND table_type = 'VIEW'
    AND NOT STARTS_WITH(table_name, 'graph_')
),
dep_paths AS (
  SELECT
    rv.target_fq_view,
    dd.fq_ref AS current_fq_object,
    1 AS depth
  FROM root_views rv
  JOIN direct_deps dd
    ON dd.fq_view = rv.target_fq_view

  UNION ALL

  SELECT
    p.target_fq_view,
    dd.fq_ref AS current_fq_object,
    p.depth + 1 AS depth
  FROM dep_paths p
  JOIN object_meta om
    ON om.fq_object = p.current_fq_object
   AND om.table_type = 'VIEW'
  JOIN direct_deps dd
    ON dd.fq_view = p.current_fq_object
  WHERE p.depth < 8
),
base_edges AS (
  SELECT
    p.current_fq_object AS source_fq_table,
    p.target_fq_view,
    MIN(p.depth) AS lineage_depth,
    COUNT(*) AS dependency_path_count
  FROM dep_paths p
  JOIN object_meta om
    ON om.fq_object = p.current_fq_object
   AND om.table_type = 'BASE TABLE'
  GROUP BY p.current_fq_object, p.target_fq_view
)
SELECT
  source_fq_table AS source_node,
  target_fq_view AS target_node,
  'BASE TABLE' AS source_type,
  'VIEW' AS target_type,
  'VIEW_LINEAGE_BASE' AS edge_method,
  dependency_path_count AS relationship_strength,
  100 AS confidence_score,
  'HIGH' AS confidence_tier,
  lineage_depth,
  CONCAT('Resolved from recursive view SQL lineage. Min depth: ', CAST(lineage_depth AS STRING)) AS evidence
FROM base_edges
