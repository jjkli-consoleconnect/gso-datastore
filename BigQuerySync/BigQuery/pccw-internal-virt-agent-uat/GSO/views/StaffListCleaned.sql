SELECT 

Staff_ID_Number, 
Staff_Name, 
CASE 
    WHEN Staff_Name LIKE '%,%' THEN TRIM(SPLIT(Staff_Name, ',')[OFFSET(0)])
    ELSE NULL
  END AS Surname,
  CASE 
    WHEN Staff_Name LIKE '%,%' THEN TRIM(SPLIT(Staff_Name, ',')[OFFSET(1)])
    ELSE NULL
  END AS Firstname,
TRIM(Team_Name) AS Team_Name, 
Team_Head, 
Sub_Team, 
Country, 
Title, 
Remark,
bigquerysignaturesearch, 
Ingestion_Time,
CASE
  WHEN title IS NULL THEN 'Manager'
  WHEN REGEXP_CONTAINS(LOWER(title),
       r'\b(engineer|eng|analyst|technician|tech|developer|developer|dev|support|specialist|operator|ops|soc|noc|service engineer|customer engineer|application support|python developer)\b')
    THEN 'Engineer'
  WHEN REGEXP_CONTAINS(LOWER(title),
       r'\b(manager|lead|supervisor|director|vice president|vp|avp|head|chief|manager,|assistant vice president|manager \(|unit manager|operations manager)\b')
    THEN 'Manager'
  ELSE 'Manager'
END AS Category1

FROM `pccw-internal-virt-agent-uat.GSO.Staff` 


