SELECT 
    t1.*,
    t2.EscalationTime, 
    t2.WorkLogSubmitterFullName AS EscalatedBy,
    t2.WorkLogType AS EscalationType,
    CASE
        WHEN t1.CaseType IN ('Problem', 'Request', 'Incident', 'Question', 'Fault Report Request') THEN t1.CaseType
        ELSE 'Maintenance'
    END AS TicketType,
    IFNULL(TIMESTAMP_DIFF(t1.Closed_Date, t1.Submit_Date, MINUTE), 0) AS TicketDuration,
    t1.trueMTTR_mins AS MTTR_Filtered,
    TIMESTAMP_DIFF(t1.Closed_Date, t1.Submit_Date, SECOND) AS LeadTime_sec,
    TIMESTAMP_DIFF(t1.Closed_Date, t1.Submit_Date, HOUR) AS LeadTime_hrs

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

