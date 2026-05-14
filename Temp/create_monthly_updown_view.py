from google.cloud import bigquery

client = bigquery.Client(project="pccw-internal-virt-agent-uat")

sql = """
CREATE OR REPLACE VIEW `pccw-internal-virt-agent-uat.GSO.CenterOps_MonthlyUpDown` AS
WITH ticket_level AS (
  -- One row per ticket per month, keep dimensions for slicing
  SELECT
    Incident_Number,
    DATE_TRUNC(DATE(COALESCE(Closed_Date, LastResolvedDate, Reported_Date)), MONTH) AS month_start,
    ANY_VALUE(SRNo) AS SRNo,
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
monthly AS (
  SELECT
    month_start,
    COALESCE(Assigned_Group, 'Unknown') AS Assigned_Group,
    COALESCE(CaseType, 'Unknown') AS CaseType,
    COALESCE(Fault_Cause, 'Unknown') AS Fault_Cause,
    COALESCE(Fault_Cause_Normalized, 'Unknown') AS Fault_Cause_Normalized,
    COALESCE(AIFaultCause, 'Unknown') AS AIFaultCause,
    COALESCE(AIAtFault, 'Unknown') AS AIAtFault,
    COALESCE(AI_FaultDomain, 'Unknown') AS AI_FaultDomain,
    COUNT(DISTINCT SRNo) AS number_of_circuits,
    COUNTIF(is_counted_fault = 1) AS counted_fault_tickets,
    SUM(CASE WHEN is_counted_fault = 1 THEN counted_mttr_mins ELSE 0 END) AS total_counted_mttr_mins
  FROM ticket_level
  GROUP BY month_start, Assigned_Group, CaseType, Fault_Cause, Fault_Cause_Normalized, AIFaultCause, AIAtFault, AI_FaultDomain
),
monthly_all AS (
  -- Overall monthly trend row (no breakdown)
  SELECT
    month_start,
    'ALL' AS Assigned_Group,
    'ALL' AS CaseType,
    'ALL' AS Fault_Cause,
    'ALL' AS Fault_Cause_Normalized,
    'ALL' AS AIFaultCause,
    'ALL' AS AIAtFault,
    'ALL' AS AI_FaultDomain,
    COUNT(DISTINCT SRNo) AS number_of_circuits,
    COUNTIF(is_counted_fault = 1) AS counted_fault_tickets,
    SUM(CASE WHEN is_counted_fault = 1 THEN counted_mttr_mins ELSE 0 END) AS total_counted_mttr_mins
  FROM ticket_level
  GROUP BY month_start
)
SELECT
  month_start,
  FORMAT_DATE('%Y-%m', month_start) AS month_year,
  Assigned_Group,
  CaseType,
  Fault_Cause,
  Fault_Cause_Normalized,
  AIFaultCause,
  AIAtFault,
  AI_FaultDomain,
  number_of_circuits,
  DATE_DIFF(DATE_ADD(month_start, INTERVAL 1 MONTH), month_start, DAY) * 1440 AS month_minutes,
  counted_fault_tickets,
  total_counted_mttr_mins,
  SAFE_DIVIDE(
    (number_of_circuits * (DATE_DIFF(DATE_ADD(month_start, INTERVAL 1 MONTH), month_start, DAY) * 1440))
      - total_counted_mttr_mins,
    number_of_circuits * (DATE_DIFF(DATE_ADD(month_start, INTERVAL 1 MONTH), month_start, DAY) * 1440)
  ) AS up_pct,
  SAFE_DIVIDE(
    total_counted_mttr_mins,
    number_of_circuits * (DATE_DIFF(DATE_ADD(month_start, INTERVAL 1 MONTH), month_start, DAY) * 1440)
  ) AS down_pct,
  SAFE_DIVIDE(counted_fault_tickets, number_of_circuits) AS fault_rate_pct
FROM (
  SELECT * FROM monthly
  UNION ALL
  SELECT * FROM monthly_all
)
WHERE number_of_circuits > 0
"""

print("Creating view GSO.CenterOps_MonthlyUpDown...")
job = client.query(sql)
job.result()
print("✓ View created successfully")
