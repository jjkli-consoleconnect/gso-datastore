SELECT
  run_date,
  run_ts,
  source_snapshot_date,
  source_snapshot_month,
  filter_version,
  filter_itemcode,
  filter_billing_type,
  filter_ctstatus,
  filter_costtype_cleaned,
  scorecard_type,
  filter_srstatus,
  filter_itemstatus,
  CASE
    WHEN scorecard_type = 'start_gap' THEN 'Start Gap'
    WHEN scorecard_type = 'stop_gap' THEN 'Stop Gap'
    ELSE scorecard_type
  END AS scorecard_label,
  total_cost_items,
  open_gap_action_required_count,
  action_required_non_no_count,
  avg_gap_duration_days,
  mrc_usd,
  estimated_gap_cost_usd,
  CASE WHEN scorecard_type = 'start_gap' THEN total_cost_items END AS start_gap_total_cost_items,
  CASE WHEN scorecard_type = 'start_gap' THEN open_gap_action_required_count END AS start_gap_open_gap_action_required_count,
  CASE WHEN scorecard_type = 'start_gap' THEN action_required_non_no_count END AS start_gap_action_required_count,
  CASE WHEN scorecard_type = 'start_gap' THEN avg_gap_duration_days END AS start_gap_avg_gap_duration_days,
  CASE WHEN scorecard_type = 'start_gap' THEN mrc_usd END AS start_gap_mrc_usd,
  CASE WHEN scorecard_type = 'start_gap' THEN estimated_gap_cost_usd END AS start_gap_estimated_gap_cost_usd,
  CASE WHEN scorecard_type = 'stop_gap' THEN total_cost_items END AS stop_gap_total_cost_items,
  CASE WHEN scorecard_type = 'stop_gap' THEN open_gap_action_required_count END AS stop_gap_open_gap_action_required_count,
  CASE WHEN scorecard_type = 'stop_gap' THEN action_required_non_no_count END AS stop_gap_action_count,
  CASE WHEN scorecard_type = 'stop_gap' THEN avg_gap_duration_days END AS stop_gap_avg_gap_duration_days,
  CASE WHEN scorecard_type = 'stop_gap' THEN mrc_usd END AS stop_gap_mrc_usd,
  CASE WHEN scorecard_type = 'stop_gap' THEN estimated_gap_cost_usd END AS stop_gap_estimated_gap_cost_usd
FROM `pccw-internal-virt-agent-uat.GSOEDPLink.CostItemSnapSnapshot`;
