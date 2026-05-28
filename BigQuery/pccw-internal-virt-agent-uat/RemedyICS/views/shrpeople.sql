SELECT 
CASE WHEN CustID = '' THEN NULL ELSE CustID END AS `CustomerID`,
CASE WHEN custname = '' THEN NULL ELSE custname END AS `CustomerName`,
SRNo, 
`Product Family`, 
SiteA, 
SiteB, 
`Region A`, 
`Region B`, 
`Product ID`, 
`Insight Circuit ID`, 
`Circuit Owner`

FROM `pccw-internal-virt-agent-uat.RemedyICS.SHRPeople` 
