SELECT
  invoice.month,
  DATE(usage_start_time) AS usage_date,
  project.id AS project_id,
  CASE
    WHEN project.id = 'pccw-internal-virt-agent-uat' THEN 'UAT'
    WHEN project.id = 'pccw-internal-virtual-agent' THEN 'Prod'
    ELSE project.name
  END AS project_name,
  service.description AS service_name,
  sku.description AS sku_name,
  location.region,
  cost AS gross_cost,
  IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS total_credits,
  cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS net_cost,
  currency,
  usage.amount AS usage_amount,
  usage.unit AS usage_unit
FROM
  `console-core-billing-data.console_core_gcp_billing_data.gcp_billing_export_resource_v1_016ABE_050539_C7586C`

