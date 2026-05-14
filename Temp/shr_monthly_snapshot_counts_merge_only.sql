MERGE `pccw-internal-virt-agent-uat.GSO.SHRPeople_StatusMonthlyCounts` t
USING (
  SELECT
    DATE_TRUNC(LAST_DAY(CURRENT_DATE(), MONTH), MONTH) AS snapshot_month,
    LAST_DAY(CURRENT_DATE(), MONTH) AS snapshot_date,
    COALESCE(SR_Status, 'Unknown') AS SR_Status,
    COALESCE(Circuit_Owner, 'Unknown') AS Circuit_Owner,
    COUNT(DISTINCT SRNo) AS sr_count,
    CURRENT_TIMESTAMP() AS updated_at
  FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople`
  WHERE CURRENT_DATE() = LAST_DAY(CURRENT_DATE(), MONTH)
  GROUP BY 1,2,3,4
) s
ON t.snapshot_month = s.snapshot_month
AND t.SR_Status = s.SR_Status
AND t.Circuit_Owner = s.Circuit_Owner
WHEN MATCHED THEN UPDATE SET
  t.snapshot_date = s.snapshot_date,
  t.sr_count = s.sr_count,
  t.updated_at = s.updated_at
WHEN NOT MATCHED THEN INSERT (
  snapshot_month,
  snapshot_date,
  SR_Status,
  Circuit_Owner,
  sr_count,
  updated_at
) VALUES (
  s.snapshot_month,
  s.snapshot_date,
  s.SR_Status,
  s.Circuit_Owner,
  s.sr_count,
  s.updated_at
);