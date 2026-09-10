@echo off
@echo off
@echo off
rem A) source vs GSOEDPLink.EDP-SR (both europe-west2) - validates scheduled query
call bq query --use_legacy_sql=false --format=csv "SELECT (SELECT COUNT(*) FROM (SELECT * FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr` EXCEPT DISTINCT SELECT * FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`)) AS src_minus_mirror, (SELECT COUNT(*) FROM (SELECT * FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR` EXCEPT DISTINCT SELECT * FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`)) AS mirror_minus_src"
rem B) per-location digest: source (west2)
call bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS rows_, ROUND(SUM(mrc_usd),2) AS sum_mrc, COUNTIF(mrc_usd IS NOT NULL) AS nonnull_mrc FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`"
rem C) per-location digest: Mirror copy (EU)
call bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS rows_, ROUND(SUM(mrc_usd),2) AS sum_mrc, COUNTIF(mrc_usd IS NOT NULL) AS nonnull_mrc FROM `pccw-internal-virt-agent-uat.Mirror.EDP-SR`"
rem D) MRC comparison against the SOURCE table directly
call bq query --use_legacy_sql=false --format=csv "WITH ci AS (SELECT CONCAT('SR', CAST(SalesRecord AS STRING)) AS sr_key, SUM(MRC_USD) AS cost_items_mrc_usd FROM `edp-prod-lake-data-warehouse.Cost_Items.all_cost_items_report` GROUP BY sr_key), edp AS (SELECT CONCAT('SR', CAST(sr_id AS STRING)) AS sr_key, mrc_usd AS edp_mrc_usd FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`) SELECT COUNT(DISTINCT e.sr_key) AS srs_in_edp_source, COUNT(DISTINCT c.sr_key) AS srs_in_cost_items, COUNTIF(ABS(IFNULL(e.edp_mrc_usd,0) - IFNULL(c.cost_items_mrc_usd,0)) < 0.01) AS matching, COUNTIF(ABS(IFNULL(e.edp_mrc_usd,0) - IFNULL(c.cost_items_mrc_usd,0)) >= 0.01) AS mismatching, ROUND(SUM(e.edp_mrc_usd),0) AS total_edp_mrc, ROUND(SUM(c.cost_items_mrc_usd),0) AS total_cost_items_mrc FROM edp e FULL OUTER JOIN ci c USING (sr_key)"

