SELECT
    Incident_Number, 
    TAC, 
    JiraStatus, 
    CASE 
        WHEN JIRAJoin.EscalatedBy IS NULL THEN NULL 
        WHEN UserIDTable.FullName IS NOT NULL THEN UserIDTable.FullName 
        ELSE JIRAJoin.EscalatedBy
    END AS EscalatedBy,  
    EscalationDate, 
    NOC
FROM
    `pccw-internal-virt-agent-uat.RemedyICS.JIRAJoin` AS JIRAJoin
LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS UserIDTable ON JIRAJoin.EscalatedBy = UserIDTable.InsightID

