SELECT
  rule_id,
  pattern_type,
  pattern_value,
  regex_flags,
  priority,
  description,
  owner,
  source_system,
  visibility_scope,
  is_active,
  updated_at,
  updated_by
FROM `pccw-internal-virtual-agent.wanda_ds.dlp_redaction_allowlist`
ORDER BY is_active DESC, priority ASC, rule_id ASC
