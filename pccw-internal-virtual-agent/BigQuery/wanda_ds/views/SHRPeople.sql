SELECT 
  CustID, 
  CustName, 
  SRNo, 
  `Product Family`, 
  `Product ID`, 
  `Insight Circuit ID`, 
  `Circuit Owner`, 
  ProductDescription, 
  `SR Status`, 
  Product_Family, 
  Product_ID, 
  Insight_Circuit_ID, 
  Circuit_Owner, 
  SR_Status, 
  RSMName 
FROM 
  `pccw-internal-virt-agent-uat.GSO.SHRPeople`

WHERE SR_Status NOT IN ('Dropped','Terminated')

