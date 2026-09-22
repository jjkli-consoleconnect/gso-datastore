-- HDWL joined with PagerDuty escalation data
-- Join key: HDWL.Incident_Number = PagerDuty.RemedyIncidentNumber
-- Each escalation policy label = 1 escalation (T4 = 4hr, T12 = 12hr, T24 = 24hr)
SELECT
  h.*,
  pd.pagerduty_escalation_count,
  pd.pagerduty_escalation_policies_used
FROM `pccw-internal-virt-agent-uat.GSO.HDWL` h
LEFT JOIN (
  SELECT
    RemedyIncidentNumber,
    COUNT(*) AS pagerduty_escalation_count,
    STRING_AGG(escalation_policy_label, ', ' ORDER BY sort_key) AS pagerduty_escalation_policies_used
  FROM (
    SELECT DISTINCT
      RemedyIncidentNumber,
      escalation_policy_label,
      CASE
        WHEN REGEXP_CONTAINS(escalation_policy_label, r'T[0-9]+') THEN CAST(REGEXP_EXTRACT(escalation_policy_label, r'T([0-9]+)') AS INT64)
        ELSE 999
      END AS sort_key
    FROM `pccw-internal-virt-agent-uat.GSO.PagerDutyIncidentCleansed`
    WHERE RemedyIncidentNumber IS NOT NULL
      AND escalation_policy_label IS NOT NULL
  )
  GROUP BY RemedyIncidentNumber
) pd
  ON h.Incident_Number = pd.RemedyIncidentNumber