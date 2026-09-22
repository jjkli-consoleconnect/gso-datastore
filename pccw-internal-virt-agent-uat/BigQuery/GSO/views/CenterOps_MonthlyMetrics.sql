WITH months AS (
  SELECT month_start
  FROM UNNEST(
    GENERATE_DATE_ARRAY(
      DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 24 MONTH), MONTH),
      DATE_TRUNC(CURRENT_DATE(), MONTH),
      INTERVAL 1 MONTH
    )
  ) AS month_start
),
circuits AS (
  -- Current active Operation circuits from SHRPeople
  SELECT COUNT(DISTINCT SRNo) AS number_of_circuits
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE SR_Status = 'Operation'
),
ticket_level AS (
  -- Deduplicate to one row per ticket for monthly KPI math
  SELECT
    Incident_Number,
    DATE_TRUNC(DATE(COALESCE(Closed_Date, LastResolvedDate, Reported_Date)), MONTH) AS month_start,
    ANY_VALUE(Assigned_Group) AS Assigned_Group,
    ANY_VALUE(CaseType) AS CaseType,
    ANY_VALUE(Fault_Cause) AS Fault_Cause,
    ANY_VALUE(Fault_Cause_Normalized) AS Fault_Cause_Normalized,
    ANY_VALUE(AIFaultCause) AS AIFaultCause,
    ANY_VALUE(AIAtFault) AS AIAtFault,
    ANY_VALUE(AI_FaultDomain) AS AI_FaultDomain,
    MAX(COALESCE(Counted_MTTR_mins, 0)) AS counted_mttr_mins,
    MAX(CASE WHEN Is_Counted_Fault THEN 1 ELSE 0 END) AS is_counted_fault
  FROM `pccw-internal-virt-agent-uat.GSO.CenterOps_CircuitMetrics`
  WHERE Incident_Number IS NOT NULL
  GROUP BY Incident_Number, month_start
),
monthly_faults AS (
  SELECT
    month_start,
    Assigned_Group,
    CaseType,
    Fault_Cause,
    Fault_Cause_Normalized,
    AIFaultCause,
    AIAtFault,
    AI_FaultDomain,
    COUNTIF(is_counted_fault = 1) AS counted_fault_tickets,
    SUM(CASE WHEN is_counted_fault = 1 THEN counted_mttr_mins ELSE 0 END) AS total_counted_mttr_mins
  FROM ticket_level
  GROUP BY month_start, Assigned_Group, CaseType, Fault_Cause, Fault_Cause_Normalized, AIFaultCause, AIAtFault, AI_FaultDomain
)
SELECT
  m.month_start,
  f.Assigned_Group,
  f.CaseType,
  f.Fault_Cause,
  f.Fault_Cause_Normalized,
  f.AIFaultCause,
  f.AIAtFault,
  f.AI_FaultDomain,
  c.number_of_circuits,
  DATE_DIFF(DATE_ADD(m.month_start, INTERVAL 1 MONTH), m.month_start, DAY) * 1440 AS month_minutes,
  COALESCE(f.counted_fault_tickets, 0) AS counted_fault_tickets,
  COALESCE(f.total_counted_mttr_mins, 0) AS total_counted_mttr_mins,
  SAFE_DIVIDE(
    (c.number_of_circuits * (DATE_DIFF(DATE_ADD(m.month_start, INTERVAL 1 MONTH), m.month_start, DAY) * 1440))
      - COALESCE(f.total_counted_mttr_mins, 0),
    c.number_of_circuits * (DATE_DIFF(DATE_ADD(m.month_start, INTERVAL 1 MONTH), m.month_start, DAY) * 1440)
  ) AS circuit_availability,
  SAFE_DIVIDE(COALESCE(f.counted_fault_tickets, 0), c.number_of_circuits) AS fault_rate,
  SAFE_DIVIDE(
    ((c.number_of_circuits * (DATE_DIFF(DATE_ADD(m.month_start, INTERVAL 1 MONTH), m.month_start, DAY) * 1440))
      - COALESCE(f.total_counted_mttr_mins, 0)) * 100,
    c.number_of_circuits * (DATE_DIFF(DATE_ADD(m.month_start, INTERVAL 1 MONTH), m.month_start, DAY) * 1440)
  ) / 100 AS circuit_availability_pct,
  SAFE_DIVIDE(COALESCE(f.counted_fault_tickets, 0), c.number_of_circuits) AS fault_rate_pct
FROM months m
CROSS JOIN circuits c
LEFT JOIN monthly_faults f
  ON f.month_start = m.month_start
ORDER BY m.month_start
