SELECT 
  CustID, 
  CustName, 
  SRNo, 
  Product_Family, 
  Product_ID, 
  Insight_Circuit_ID, 
  Circuit_Owner, 
  ProductDescription, 
  SR_Status, 
  RSMName 
FROM 
  `pccw-internal-virt-agent-uat.GSO.SHRPeople`

WHERE SR_Status NOT IN ('Dropped','Terminated')
