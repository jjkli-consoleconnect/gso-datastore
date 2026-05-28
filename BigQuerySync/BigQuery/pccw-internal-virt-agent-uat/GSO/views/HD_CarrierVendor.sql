SELECT 
    t1.*,
    t2.EscalationTime, 
    t2.WorkLogSubmitterFullName AS EscalatedBy,
    t2.WorkLogType AS EscalationType
FROM 
    `pccw-internal-virt-agent-uat.GSO.HelpDeskAllNOC` AS t1
LEFT JOIN 
    (SELECT 
        Incident_Number, 
        MIN(WorkLog_Submit_Date) AS EscalationTime, 
        WorkLog_Submitter AS WorkLogSubmitterFullName,
        WorkLog_Type AS WorkLogType
    FROM 
        `pccw-internal-virt-agent-uat.GSO.WorkLogAllNOC`
    WHERE 
        WorkLog_Type LIKE '%Carrier%'
        AND WorkLog_Submitter != 'AR_ESCALATOR'
    GROUP BY 
        Incident_Number, WorkLogSubmitterFullName, WorkLogType
    ) AS t2
ON 
    t1.Incident_Number = t2.Incident_Number

