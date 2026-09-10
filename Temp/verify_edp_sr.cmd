@echo off
bq query --use_legacy_sql=false --format=csv "SELECT (SELECT COUNT(*) FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`) AS source_rows, (SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`) AS mirror_rows"
