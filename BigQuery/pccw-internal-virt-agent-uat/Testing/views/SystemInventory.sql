SELECT
  ID,
  InventoryCode AS System,
  CASE
    WHEN SAFE.SUBSTR(ItemSubCat, 1, 1) BETWEEN 'A' AND 'Z'
          OR SAFE.SUBSTR(ItemSubCat, 1, 1) BETWEEN 'a' AND 'z' THEN ItemSubCat
    ELSE REGEXP_EXTRACT(InventoryCode, r'^(.+?)(?:-Unknown|\s|$)')
  END AS SystemShort,
FROM
  `pccw-internal-virt-agent-uat`.`SubCableEvents`.`CableInventory`
WHERE
  Nomenclature = 'SYSTEM'
