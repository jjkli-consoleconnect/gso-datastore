WITH gsdt_jira_flattened AS (
  SELECT
    * EXCEPT(SR_Ref),
    CONCAT('SR', TRIM(SR_Ref)) AS SRno
  FROM `pccw-internal-virt-agent-uat.GSO.JiraCombined`
  WHERE `Project` = 'Global Service Delivery Team'
)
SELECT
  a.*,
  b.* EXCEPT(SRno)
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople` a
LEFT JOIN gsdt_jira_flattened b
  ON a.SRNo = b.SRno
