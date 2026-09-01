SELECT 

ProductID, 
EpicorProductID, 
ProductDescription, 
Product_Family_Remapping__based_on_Alison___Soumya_Charm_exercise_ AS ProductFamily,
CONCAT(ProductID," - ",ProductDescription) AS Prod_ID_Description


 FROM `pccw-internal-virt-agent-uat.RemedyICS.ProductCode`
