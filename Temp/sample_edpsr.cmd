@echo off
bq query --use_legacy_sql=false --format=csv "SELECT sr_id, product_id, product_family, product_description FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR` WHERE product_id IS NOT NULL LIMIT 5"
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS total, COUNT(DISTINCT sr_id) AS distinct_sr FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`"
