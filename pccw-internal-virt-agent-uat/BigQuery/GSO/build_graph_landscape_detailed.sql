-- Strict lineage graph for pccw-internal-virt-agent-uat.GSO
-- Rule enforced: source nodes are BASE TABLEs, target nodes are VIEWs.
-- Run with:
-- bq query --location=EU --use_legacy_sql=false < build_graph_landscape_detailed.sql

CREATE OR REPLACE VIEW `pccw-internal-virt-agent-uat.GSO.graph_landscape_detailed` AS
WITH RECURSIVE
table_meta AS (
  SELECT table_name, table_type
  FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.TABLES`
  WHERE NOT STARTS_WITH(table_name, 'graph_')
),
view_defs AS (
  SELECT table_name AS view_name, view_definition
  FROM `pccw-internal-virt-agent-uat.GSO.INFORMATION_SCHEMA.VIEWS`
),
direct_deps AS (
  SELECT DISTINCT
    vd.view_name,
    SPLIT(ref, '.')[OFFSET(2)] AS referenced_object
  FROM view_defs vd
  CROSS JOIN UNNEST(REGEXP_EXTRACT_ALL(vd.view_definition, r'`([^`]+)`')) AS ref
  WHERE STARTS_WITH(ref, 'pccw-internal-virt-agent-uat.GSO.')
    AND SPLIT(ref, '.')[OFFSET(2)] != vd.view_name
),
dep_paths AS (
  SELECT
    d.view_name AS target_view,
    d.referenced_object AS current_object,
    1 AS depth
  FROM direct_deps d

  UNION ALL

  SELECT
    p.target_view,
    d.referenced_object AS current_object,
    p.depth + 1 AS depth
  FROM dep_paths p
  JOIN table_meta tm
    ON tm.table_name = p.current_object
   AND tm.table_type = 'VIEW'
  JOIN direct_deps d
    ON d.view_name = p.current_object
  WHERE p.depth < 8
),
base_edges AS (
  SELECT
    p.target_view,
    p.current_object AS source_table,
    MIN(p.depth) AS min_depth,
    COUNT(*) AS dependency_path_count
  FROM dep_paths p
  JOIN table_meta tm
    ON tm.table_name = p.current_object
   AND tm.table_type = 'BASE TABLE'
  GROUP BY p.target_view, p.current_object
)
SELECT
  CONCAT('GSO.', b.source_table) AS source_node,
  CONCAT('GSO.', b.target_view) AS target_node,
  'BASE TABLE' AS source_type,
  'VIEW' AS target_type,
  'VIEW_LINEAGE_BASE' AS edge_method,
  b.dependency_path_count AS relationship_strength,
  100 AS confidence_score,
  'HIGH' AS confidence_tier,
  b.min_depth AS lineage_depth,
  CONCAT('Resolved from view SQL lineage. Min depth: ', CAST(b.min_depth AS STRING)) AS evidence
FROM base_edges b;

-- Validation checks
SELECT source_type, target_type, edge_method, COUNT(*) AS edges
FROM `pccw-internal-virt-agent-uat.GSO.graph_landscape_detailed`
GROUP BY source_type, target_type, edge_method;

SELECT source_node, target_node, relationship_strength, lineage_depth
FROM `pccw-internal-virt-agent-uat.GSO.graph_landscape_detailed`
WHERE target_node = 'GSO.GSDT_Cleaned'
ORDER BY source_node;
