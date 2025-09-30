SELECT
  t1.InventoryCode AS System,
  t2.InventoryCode AS Segment
FROM
  `pccw-internal-virt-agent-uat`.`SubCableEvents`.`CableInventory` AS t1
INNER JOIN
  `pccw-internal-virt-agent-uat`.`SubCableEvents`.`CableInventory` AS t2
ON
  t2.Parent = t1.ID
WHERE
  t1.Nomenclature = 'SYSTEM'
  AND t2.Nomenclature = 'SEGMENT';
