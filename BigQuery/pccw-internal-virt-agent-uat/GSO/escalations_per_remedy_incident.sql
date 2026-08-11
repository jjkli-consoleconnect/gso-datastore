-- Escalations per Remedy Incident Number
-- Each escalation policy label = 1 escalation (T4 = 4hr, T12 = 12hr, T24 = 24hr)
-- Each label can only be used once per Remedy incident, so count distinct labels
-- Sorted by escalation time: T4 < T12 < T24
-- Copy and paste this into BigQuery
SELECT
  RemedyIncidentNumber,
  COUNT(*) AS escalation_count,
  STRING_AGG(escalation_policy_label, ', ' ORDER BY sort_key) AS escalation_policies_used
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
ORDER BY escalation_count DESC