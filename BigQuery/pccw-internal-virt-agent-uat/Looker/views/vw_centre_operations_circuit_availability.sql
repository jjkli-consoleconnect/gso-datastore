WITH
  calendar AS (
    -- 1. Generate the monthly list for the past 24 months, dynamically adjusting the effective minutes for the start month (June 2026)
    SELECT
      month_start,
      -- If it is June 2026, count from the 11th (20 days total); otherwise, maintain full month days
      CASE
        WHEN month_start = '2026-06-01'
          THEN DATE_DIFF(DATE('2026-07-01'), DATE('2026-06-11'), DAY) * 24 * 60
        ELSE
          DATE_DIFF(DATE_ADD(month_start, INTERVAL 1 MONTH), month_start, DAY)
          * 24
          * 60
        END
        AS month_minutes
    FROM
      UNNEST(
        GENERATE_DATE_ARRAY(
          DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 23 MONTH), MONTH),
          DATE_TRUNC(CURRENT_DATE(), MONTH),
          INTERVAL 1 MONTH))
        AS month_start
    WHERE
      month_start
      >= '2026-06-01'  -- Restrict to months from June 2026 (data collection start point) onwards
  ),
  active_sr_monthly AS (
    -- 2. Calculate the number of operating circuits per month
    SELECT
      DATE_TRUNC(batch_date, MONTH) AS month_start,
      AVG(distinct_sr_count) AS active_circuits
    FROM `pccw-internal-virt-agent-uat.sheldon_testing.Active_SR_Count`
    WHERE sr_status = 'Operation'
    GROUP BY 1
  ),
  jira_monthly AS (
    -- 3. Calculate total MTTR and distinct fault SR count per month from JIRA_HD
    SELECT
      DATE(DATE_TRUNC(Closed_Date, MONTH)) AS month_start,
      SRno,
      SUM(TrueMTTR_mins) AS total_mttr_mins
    FROM `pccw-internal-virt-agent-uat.GSO.JIRA_HD`
    WHERE Closed_Date IS NOT NULL AND SRno IS NOT NULL AND CaseType = "Incident"
    GROUP BY 1, 2
  ),
  aggregated_jira AS (
    -- 4. Aggregate JIRA data to the month level
    SELECT
      month_start,
      COUNT(DISTINCT SRno) AS counted_fault_tickets,
      SUM(total_mttr_mins) AS total_mttr_mins
    FROM jira_monthly
    GROUP BY 1
  ),
  combined_metrics AS (
    -- 5. Combine calendar, circuit counts, and JIRA fault data
    SELECT
      c.month_start,
      COALESCE(a.active_circuits, 0) AS active_circuits,
      COALESCE(j.counted_fault_tickets, 0) AS counted_fault_tickets,
      COALESCE(j.total_mttr_mins, 0) AS total_mttr_mins,
      c.month_minutes
    FROM calendar c
    LEFT JOIN active_sr_monthly a
      ON c.month_start = a.month_start
    LEFT JOIN aggregated_jira j
      ON c.month_start = j.month_start
  ),
  -- 6. Calculate final metrics: Circuit Availability and Fault Rate
  final AS (
    SELECT
      month_start,
      active_circuits,
      counted_fault_tickets,
      month_minutes,
      SAFE_DIVIDE(
        (active_circuits * month_minutes) - total_mttr_mins,
        active_circuits * month_minutes)
        AS circuit_availability,
      SAFE_DIVIDE(counted_fault_tickets, active_circuits) AS fault_rate
    FROM combined_metrics
  )
SELECT * FROM final ORDER BY month_start DESC;


