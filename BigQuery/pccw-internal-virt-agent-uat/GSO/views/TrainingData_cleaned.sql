SELECT DISTINCT


First_Name, 
Last_Name, 
Middle_Name, 
User_Legal_Name, 
CASE 
    WHEN Email_Address = 'zpaclibar@pccwglobal.com' THEN 'zpaclibar@consoleconnect.com'
    WHEN Email_Address = 'JoanColleen.Katipunan@pccw.com' THEN 'jckatipunan@consoleconnect.com'
    WHEN Email_Address = 'Jann-Kevin.Rayco@pccw.com' THEN 'jkrayco@consoleconnect.com'
    WHEN Email_Address = 'Hin-Ming.Mak@pccw.com' THEN 'hmmak@consoleconnect.com'
    ELSE Email_Address
END AS Email_Address, 
REGEXP_SUBSTR(LOWER(Email_Address), '^[^@]+') AS UserID,
Division, 
Department, 
Team, 
Item_Title,




FROM `pccw-internal-virt-agent-uat.GSO.TrainingData` 
