WITH ordered AS (
  SELECT
    cl.Issue_Key,
    cl.Transition_Timestamp,
    cl.Transitioned_From,
    cl.Transitioned_To,
    hd.Created,
    hd.Resolved,
    hd.JiraStatus AS current_status,
    -- next transition in time order (when we leave the status we just entered)
    LEAD(cl.Transition_Timestamp) OVER (
      PARTITION BY cl.Issue_Key
      ORDER BY cl.Transition_Timestamp
    ) AS next_transition,
    ROW_NUMBER() OVER (
      PARTITION BY cl.Issue_Key
      ORDER BY cl.Transition_Timestamp
    ) AS row_num
  FROM `pccw-internal-virt-agent-uat.GSO.JiraChangelog` cl
  LEFT JOIN `pccw-internal-virt-agent-uat.GSO.JIRA_HD` hd
    ON cl.Issue_Key = hd.Key
  WHERE cl.Issue_Key LIKE 'CCAS%'
     OR cl.Issue_Key LIKE 'TAC%'
     OR cl.Issue_Key LIKE 'VOICECE%'
     OR cl.Issue_Key LIKE 'IOTCE%'
     OR cl.Issue_Key LIKE 'TXCE%'
     OR cl.Issue_Key LIKE 'SMSCE%'
),
entered_status AS (
  -- duration in the status that starts at each transition
  SELECT
    Issue_Key,
    Transitioned_To AS status_label,
    Transition_Timestamp AS status_start,
    COALESCE(next_transition, Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM ordered
  WHERE Transitioned_To IS NOT NULL
),
initial_status AS (
  -- initial state from ticket creation until the first logged transition
  SELECT
    Issue_Key,
    COALESCE(Transitioned_From, current_status, 'Created (unknown)') AS status_label,
    Created AS status_start,
    Transition_Timestamp AS status_end
  FROM ordered
  WHERE row_num = 1
    AND Transition_Timestamp IS NOT NULL
),
no_changelog AS (
  -- tickets that never had a transition recorded
  SELECT
    hd.Key AS Issue_Key,
    hd.JiraStatus AS status_label,
    hd.Created AS status_start,
    COALESCE(hd.Resolved, CURRENT_TIMESTAMP()) AS status_end
  FROM `pccw-internal-virt-agent-uat.GSO.JIRA_HD` hd
  WHERE (hd.Key LIKE 'CCAS%' OR hd.Key LIKE 'TAC%' OR hd.Key LIKE 'VOICECE%' OR hd.Key LIKE 'IOTCE%' OR hd.Key LIKE 'TXCE%' OR hd.Key LIKE 'SMSCE%')
    AND NOT EXISTS (
      SELECT 1 FROM ordered o WHERE o.Issue_Key = hd.Key
    )
),
durations AS (
  SELECT * FROM entered_status
  UNION ALL
  SELECT * FROM initial_status
  UNION ALL
  SELECT * FROM no_changelog
),
filtered_durations AS (
  SELECT *
  FROM durations
  WHERE status_start IS NOT NULL
    AND status_end IS NOT NULL
    AND status_start < status_end
)
SELECT
  hd.*,
  filtered_durations.Issue_Key,
  filtered_durations.status_label,
  filtered_durations.status_start,
  filtered_durations.status_end,
  TIMESTAMP_DIFF(filtered_durations.status_end, filtered_durations.status_start, MINUTE) AS status_duration_minutes
FROM `pccw-internal-virt-agent-uat.GSO.JIRA_HD` hd
LEFT JOIN filtered_durations
  ON filtered_durations.Issue_Key = hd.Key
WHERE REGEXP_CONTAINS(hd.Key, r'^(CCAS|TAC|VOICECE|IOTCE|TXCE|SMSCE)')
ORDER BY hd.Key, filtered_durations.status_start;

