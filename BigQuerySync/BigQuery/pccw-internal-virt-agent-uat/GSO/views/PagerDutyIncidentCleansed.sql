SELECT 
  incident_id,
  incident_number,
  incident_type,
  title,
  description,
  urgency,
  priority,
  service_id,
  service_name,
  escalation_policy_id,
  escalation_policy_name,
  -- Add friendly label mapping here
  CASE
    WHEN escalation_policy_name = "CCAS Jira Project-ep" THEN "CCAS"
    WHEN escalation_policy_name = "CCPROV-ep" THEN "CCPROV"
    WHEN escalation_policy_name = "IP Network (TAC)" THEN "TAC"
    WHEN escalation_policy_name = "ithd-ir-fr-ep-v1" THEN "ITHD-FR"
    WHEN escalation_policy_name = "ithd-ir-ep-v1" THEN "ITHD"
    WHEN escalation_policy_name = "Mobility IOT - CE Jira Project (IOTCE)-ep" THEN "IOTCE"
    WHEN escalation_policy_name = "Mobility SMS - CE Jira Project (SMSCE)-ep" THEN "SMSCE"
    WHEN escalation_policy_name = "Security Incident Escalation Policy" THEN "SecurityIncident"
    WHEN escalation_policy_name = "TXCE" THEN "TXCE"
    WHEN escalation_policy_name = "Remedy ticket escalation policy" THEN "RemedyEscalation"
    WHEN escalation_policy_name = "CO - T4 - Console Support Escalation Policy" THEN "ConsoleSupport-T4"
    WHEN escalation_policy_name = "CO - T12 - Console Support Escalation Policy" THEN "ConsoleSupport-T12"
    WHEN escalation_policy_name = "CO - T24 - Console Support Escalation Policy" THEN "ConsoleSupport-T24"
    WHEN escalation_policy_name = "CO - T4 - PHSOC Escalation Policy" THEN "PHSOC-T4"
    WHEN escalation_policy_name = "CO - T12 - PHSOC Escalation Policy" THEN "PHSOC-T12"
    WHEN escalation_policy_name = "CO - T24 - PHSOC Escalation Policy" THEN "PHSOC-T24"
    WHEN escalation_policy_name = "CO - T4 - HKFMC Escalation Policy" THEN "HKFMC-T4"
    WHEN escalation_policy_name = "CO - T12 - HKFMC - Escalation Policy" THEN "HKFMC-T12"
    WHEN escalation_policy_name = "CO - T24 - HKFMC - Escalation Policy" THEN "HKFMC-T24"
    WHEN escalation_policy_name = "CO - T4 - GSOC Escalation Policy" THEN "GSOC-T4"
    WHEN escalation_policy_name = "CO - T12 - GSOC Escalation Policy" THEN "GSOC-T12"
    WHEN escalation_policy_name = "CO - T24 - GSOC Escalation Policy" THEN "GSOC-T24"
    WHEN escalation_policy_name = "CO - T4 - ICX Escalation Policy" THEN "ICX-T4"
    WHEN escalation_policy_name = "CO - T12 - ICX Escalation Policy" THEN "ICX-T12"
    WHEN escalation_policy_name = "CO - T24 - ICX Escalation Policy" THEN "ICX-T24"
    WHEN escalation_policy_name = "CO - T4 - Cable NOC Escalation Policy" THEN "CableNOC-T4"
    WHEN escalation_policy_name = "CO - T12 - Cable NOC Escalation Policy" THEN "CableNOC-T12"
    WHEN escalation_policy_name = "CO - T24 - Cable NOC Escalation Policy" THEN "CableNOC-T24"
    WHEN escalation_policy_name = "CO - T4 - Voice NOC Escalation Policy" THEN "VoiceNOC-T4"
    WHEN escalation_policy_name = "CO - T12 - Voice NOC Service-ep" THEN "VoiceNOC-T12"
    WHEN escalation_policy_name = "CO - T24 - Voice NOC Service-ep" THEN "VoiceNOC-T24"
    WHEN escalation_policy_name = "CO - T4 - Satellite NOC Escalation Policy" THEN "SatelliteNOC-T4"
    WHEN escalation_policy_name = "CO - T12 - Satellite NOC Escalation Policy" THEN "SatelliteNOC-T12"
    WHEN escalation_policy_name = "CO - T24 - Satellite NOC Escalation Policy" THEN "SatelliteNOC-T24"
    WHEN escalation_policy_name = "CO - T4 - US NOC Escalation Policy" THEN "USNOC-T4"
    WHEN escalation_policy_name = "CO - T12 - US NOC Escalation Policy" THEN "USNOC-T12"
    WHEN escalation_policy_name = "CO - T24 - US NOC Escalation Policy" THEN "USNOC-T24"
    WHEN escalation_policy_name = "CO - T4 - Security NOC Escalation Policy" THEN "SecurityNOC-T4"
    WHEN escalation_policy_name = "CO - T12 - Security NOC Escalation Policy" THEN "SecurityNOC-T12"
    WHEN escalation_policy_name = "CO - T24 - Security NOC Escalation Policy" THEN "SecurityNOC-T24"
    WHEN escalation_policy_name LIKE "CO - T4 - Belgium NOC%" THEN "BelNOC-T4"
    WHEN escalation_policy_name LIKE "CO - T12 - Belgium NOC%" THEN "BelNOC-T12"
    WHEN escalation_policy_name LIKE "CO - T24 - Belgium NOC%" THEN "BelNOC-T24"
    ELSE escalation_policy_name
  END AS escalation_policy_label,
  
  created_at AS incident_created_at,
  created_at_hkt AS incident_created_at_hkt,
  first_trigger_time,
  acknowledgement_time,
  acknowledged_by,
  resolved_at,
  resolved_by,
  auto_resolved,
  last_status_update_at,
  incident_key,
  responders_display,
  tta_seconds,
  ttr_seconds,
  response_effort_seconds,
  escalations_count,
  assignees_json,

  responders[SAFE_OFFSET(0)].responder_id AS first_responder_id,
  responders[SAFE_OFFSET(0)].responder_name AS first_responder_name,
  responders[SAFE_OFFSET(0)].responder_email AS first_responder_email,
  responders[SAFE_OFFSET(0)].responder_type AS first_responder_type,
  responders[SAFE_OFFSET(0)].responder_teams_json AS first_responder_teams_json,

  responder_metrics[SAFE_OFFSET(0)].responder AS first_responder_metric,
  responder_metrics[SAFE_OFFSET(0)].team AS first_responder_team,
  responder_metrics[SAFE_OFFSET(0)].incidents AS first_responder_incidents,
  responder_metrics[SAFE_OFFSET(0)].acknowledged_incidents AS first_responder_acknowledged_incidents,
  responder_metrics[SAFE_OFFSET(0)].acknowledged_incidents_pct AS first_responder_ack_pct,
  responder_metrics[SAFE_OFFSET(0)].interruptions AS first_responder_interruptions,
  responder_metrics[SAFE_OFFSET(0)].notifications AS first_responder_notifications,
  responder_metrics[SAFE_OFFSET(0)].mtta_seconds AS first_responder_mtta_seconds,
  responder_metrics[SAFE_OFFSET(0)].mttr_seconds AS first_responder_mttr_seconds,
  responder_metrics[SAFE_OFFSET(0)].response_effort_seconds AS first_responder_response_effort_seconds,
  responder_metrics[SAFE_OFFSET(0)].timeout_escalated_incidents AS first_responder_timeout_escalations,
  responder_metrics[SAFE_OFFSET(0)].manually_escalated_incidents AS first_responder_manual_escalations,

  service_performance.service AS service_perf_service,
  service_performance.team AS service_perf_team,
  service_performance.escalation_policy AS service_perf_escalation_policy,
  service_performance.uptime_pct AS service_perf_uptime_pct,
  service_performance.incidents AS service_perf_incidents,
  service_performance.acknowledged_incidents AS service_perf_acknowledged_incidents,
  service_performance.acknowledged_incidents_pct AS service_perf_ack_pct,
  service_performance.auto_resolved_incidents AS service_perf_auto_resolved_incidents,
  service_performance.auto_resolved_incidents_pct AS service_perf_auto_resolved_pct,
  service_performance.mtta_seconds AS service_perf_mtta_seconds,
  service_performance.mttr_seconds AS service_perf_mttr_seconds,
  service_performance.response_effort_seconds AS service_perf_response_effort_seconds,
  service_performance.total_escalations AS service_perf_total_escalations,

  jj_test_custom_field,
  jira_issue,
  custom_fields_json,

  log_entries[SAFE_OFFSET(0)].entry_type AS first_log_entry_type,
  log_entries[SAFE_OFFSET(0)].created_at AS first_log_entry_created_at,
  log_entries[SAFE_OFFSET(0)].actor_type AS first_log_actor_type,
  log_entries[SAFE_OFFSET(0)].actor_id AS first_log_actor_id,
  log_entries[SAFE_OFFSET(0)].actor_summary AS first_log_actor_summary,

  html_url,
  sync_time,
  status
FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentData`


