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
    WHEN Email_Address = 'Rollon.LeopoldoJr@pccw.com' THEN 'lrollonfr@consoleconnect.com'
    WHEN Email_Address = 'Sheldon.WY.Lo@pccw.com' THEN 'swylo@consoleconnect.com'
    WHEN Email_Address = 'Chun-Kwong.Mak@pccw.com' THEN 'ckmak@consoleconnect.com'
    WHEN Email_Address = 'Alvin.WH.Chan@pccw.com' THEN 'wchan2@consoleconnect.com'
    WHEN Email_Address = 'chun-yim.hui@pccw.com' THEN 'cyhui@consoleconnect.com'
    WHEN Email_Address = 'Andie.WH.Yu@pccw.com' THEN 'whyu@consoleconnect.com'
    WHEN Email_Address = 'amy.my.chiang@pccw.com' THEN 'amychiang@consoleconnect.com'
    WHEN Email_Address = 'Kenneth.TK.Chan@pccw.com' THEN 'tkchan@consoleconnect.com'
    WHEN Email_Address = 'Marco.CH.Li@pccw.com' THEN 'marcoli@consoleconnect.com'
    WHEN Email_Address = 'ArianKenneth.Evangelista@pccw.com' THEN 'aevangelista@consoleconnect.com'
    WHEN Email_Address = 'kmagnaye@pccwglobal.com' THEN 'kmagnaye@consoleconnect.com'
    WHEN Email_Address = "Tony.PF.So@pccw.com" THEN "tso@consoleconnect.com"
    WHEN Email_Address = "Taylor.SW.Cheng@pccw.com" THEN "ctaylorsw@consoleconnect.com"
    WHEN Email_Address= "Wah-Wai.Tong@pccw.com" THEN "wwtong@consoleconnect.com"
    ELSE Email_Address
END AS Email_Address, 
REGEXP_SUBSTR(LOWER(Email_Address), '^[^@]+') AS UserID,
Division, 
Department, 
Team, 
Item_Title AS TrainingTitle,
Completion_Date,
CASE 
    WHEN Email_Address = 'zpaclibar@pccwglobal.com' THEN 'zpaclibar@consoleconnect.com'
    WHEN Email_Address = 'JoanColleen.Katipunan@pccw.com' THEN 'jckatipunan@consoleconnect.com'
    WHEN Email_Address = 'Jann-Kevin.Rayco@pccw.com' THEN 'jkrayco@consoleconnect.com'
    WHEN Email_Address = 'Hin-Ming.Mak@pccw.com' THEN 'hmmak@consoleconnect.com'
    WHEN Email_Address = 'Rollon.LeopoldoJr@pccw.com' THEN 'lrollonfr@consoleconnect.com'
    WHEN Email_Address = 'Sheldon.WY.Lo@pccw.com' THEN 'swylo@consoleconnect.com'
    WHEN Email_Address = 'Chun-Kwong.Mak@pccw.com' THEN 'ckmak@consoleconnect.com'
    WHEN Email_Address = 'Alvin.WH.Chan@pccw.com' THEN 'wchan2@consoleconnect.com'
    WHEN Email_Address = 'chun-yim.hui@pccw.com' THEN 'cyhui@consoleconnect.com'
    WHEN Email_Address = 'Andie.WH.Yu@pccw.com' THEN 'whyu@consoleconnect.com'
    WHEN Email_Address = 'amy.my.chiang@pccw.com' THEN 'amychiang@consoleconnect.com'
    WHEN Email_Address = 'Kenneth.TK.Chan@pccw.com' THEN 'tkchan@consoleconnect.com'
    WHEN Email_Address = 'Marco.CH.Li@pccw.com' THEN 'marcoli@consoleconnect.com'
    WHEN Email_Address = 'ArianKenneth.Evangelista@pccw.com' THEN 'aevangelista@consoleconnect.com'
    WHEN Email_Address = 'kmagnaye@pccwglobal.com' THEN 'kmagnaye@consoleconnect.com'
    WHEN Email_Address = "Tony.PF.So@pccw.com" THEN "tso@consoleconnect.com"
    WHEN Email_Address = "Taylor.SW.Cheng@pccw.com" THEN "ctaylorsw@consoleconnect.com"
    WHEN Email_Address= "Wah-Wai.Tong@pccw.com" THEN "wwtong@consoleconnect.com"
    ELSE CONCAT(REGEXP_SUBSTR(LOWER(Email_Address), '^[^@]+'), '@consoleconnect.com')
END AS ConsoleConnectEmailAddress



FROM `pccw-internal-virt-agent-uat.GSO.TrainingData` 
