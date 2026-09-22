-- Daily mirror of the EDP SR hub table into GSOEDPLink.EDP-SR.
-- Transfer config: projects/14417857267/locations/europe-west2/transferConfigs/6aa1ff96-0000-2c08-8faf-d4f547f94300
-- ("EDP-SR-daily-mirror", schedule "every day 23:00" UTC = 07:00 HKT).
-- Fully replaces the target each run so it mirrors the source exactly.


SET @@query_label = "seeds_environment:uat,seeds_product:edp_sr_mirror,seeds_component:bigquery";

CREATE OR REPLACE TABLE `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`
CLUSTER BY sr_id, status_name, sales_region
AS
SELECT *
FROM `edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr`;
