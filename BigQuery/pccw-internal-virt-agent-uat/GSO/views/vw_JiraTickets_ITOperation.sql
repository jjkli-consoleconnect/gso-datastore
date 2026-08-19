WITH base AS (SELECT 
  *,
  -- 提取并格式化开始日期 (Start Date)
  CASE WHEN T='Leave Request' THEN 
    PARSE_DATE("%d/%m/%Y", 
        COALESCE(
          REGEXP_EXTRACT(summary, r'(\d{2}/\d{2}/\d{4}) to'), 
          REGEXP_EXTRACT(summary, r'(\d{2}/\d{2}/\d{4})')
        )
      ) 
    ELSE  DATE(created)
  END AS start_date,
  
  -- 提取并格式化结束日期 (End Date)
  SAFE.PARSE_DATE("%d/%m/%Y", REGEXP_EXTRACT(summary, r'to (\d{2}/\d{2}/\d{4})')) AS end_date,

  CASE WHEN T='Leave Request' THEN 
      CASE 
        WHEN REGEXP_CONTAINS(summary, r'\d{2}/\d{2}/\d{4} to \d{2}/\d{2}/\d{4}') THEN
        (
          SELECT COUNT(*) 
          FROM UNNEST(GENERATE_DATE_ARRAY(
            PARSE_DATE("%d/%m/%Y", REGEXP_EXTRACT(summary, r'(\d{2}/\d{2}/\d{4}) to')),
            PARSE_DATE("%d/%m/%Y", REGEXP_EXTRACT(summary, r'to (\d{2}/\d{2}/\d{4})'))
          )) AS d
          WHERE EXTRACT(DAYOFWEEK FROM d) NOT IN (1, 7)
        ) * 8
        WHEN REGEXP_CONTAINS(summary, r'(?i)(Morning|Afternoon)') THEN 4
        WHEN REGEXP_CONTAINS(summary, r'\d{2}/\d{2}/\d{4}') THEN 8
        ELSE 0
      END 
      ELSE TimeSpentSeconds/3600
  END AS TimeSpentHours,

  CASE WHEN T='Leave Request' THEN 
      CASE
        WHEN REGEXP_CONTAINS(summary, r'(?i)training') THEN 'Training'
        WHEN REGEXP_CONTAINS(summary, r'(?i)travel|trip') THEN 'Travelling'
        ELSE 'Leave'
      END 
  ELSE T END AS leave_remarks

FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets` 
WHERE `Project` = "IT Operations")


SELECT 
  t.* EXCEPT(TimeSpentHours),
  -- 逻辑：如果是有区间的请假，按工作日平摊；否则直接取值
  CASE 
    WHEN t.T = "Leave Request" AND t.end_date IS NOT NULL THEN
      SAFE_DIVIDE(
        t.TimeSpentHours, 
        (
          SELECT COUNT(*) 
          FROM UNNEST(GENERATE_DATE_ARRAY(start_date, end_date)) AS d_range
          WHERE EXTRACT(DAYOFWEEK FROM d_range) NOT IN (1, 7)
        )
      )
    ELSE t.TimeSpentHours 
  END AS TimeSpentHours,
  d AS work_date
FROM base t
CROSS JOIN UNNEST(
  GENERATE_DATE_ARRAY(
    COALESCE(start_date, CURRENT_DATE()), 
    COALESCE(end_date, start_date, CURRENT_DATE())
  )
) AS d
WHERE 
  (t.T = 'Leave Request' AND EXTRACT(DAYOFWEEK FROM d) NOT IN (1, 7))
  OR (t.T != 'Leave Request')
