WITH gsdt_jira_flattened AS (
  SELECT
    * EXCEPT(SR_Ref),
    CONCAT('SR', TRIM(SR_Ref)) AS SRno
  FROM `pccw-internal-virt-agent-uat.GSO.JiraCombined`
  WHERE `Project` = 'Global Service Delivery Team'
)
SELECT
  a.* EXCEPT(`Product Family`, `Product ID`, `Insight Circuit ID`, `Circuit Owner`, `SR Status`),
  b.* EXCEPT(SRno)
FROM `pccw-internal-virt-agent-uat.GSO.SHRPeople` a
LEFT JOIN gsdt_jira_flattened b
  ON a.SRNo = b.SRno
--WHERE a.SR_Status IN ('Pending', 'Operation', 'Provisioning')
