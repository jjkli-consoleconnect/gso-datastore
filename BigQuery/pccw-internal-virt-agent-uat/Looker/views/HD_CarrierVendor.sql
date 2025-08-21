SELECT 
    t1.*,
    t2.EscalationTime, 
    t2.WorkLogSubmitterFullName AS EscalatedBy,
    t2.WorkLogType AS EscalationType
FROM 
    `pccw-internal-virt-agent-uat.Looker.helpdesk` AS t1
LEFT JOIN 
    (SELECT 
        IncidentNumber, 
        MIN(WorkLogSubmitDate) AS EscalationTime, 
        WorkLogSubmitterFullName,
        WorkLogType
    FROM 
        `pccw-internal-virt-agent-uat.Looker.WorkLog`
    WHERE 
        WorkLogType LIKE '%Carrier%'
        AND WorkLogSubmitter != 'AR_ESCALATOR'
    GROUP BY 
        IncidentNumber, WorkLogSubmitterFullName, WorkLogType
    ) AS t2
ON 
    t1.Incident_Number = t2.IncidentNumber

