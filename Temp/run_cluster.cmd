@echo off
call bq query --use_legacy_sql=false --format=prettyjson "DROP TABLE `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`"
call bq query --use_legacy_sql=false --format=prettyjson "CREATE OR REPLACE TABLE `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR` CLUSTER BY sr_id, status_name, sales_region AS SELECT * FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`"
