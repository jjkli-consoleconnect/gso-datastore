SELECT 
    T, 
    CASE 
        WHEN T = 'Ad-hoc provisioning' THEN 'Ad-hoc Prov'
        WHEN T = 'Customer Onboarding' THEN 'Cust Onb'
        WHEN T = 'Hybrid Onboarding' THEN 'Hybrid Onb'
        WHEN T = 'IX Service Request' THEN 'IX Serv Req'
        WHEN T = 'Port Provisioning' THEN 'Port Prov'
        WHEN T = 'Incoming Notification' THEN 'Inc Notif'
        WHEN T = 'Edge port' THEN 'Edge Port'
        WHEN T = 'CloudRouter' THEN 'Cloud Router'
        ELSE T 
    END AS IssueTypes,
    `Project`, 
    `Key`, 
    Summary, 
    Status,
    Updated,
    Created,
    Resolved,
    Reporter, 
    Assignee,
    Creator, 
    `Port Prov Status`, 
    `On-Board Checklist` AS OnboardChecklist, 
    `Onboard Category` AS OnboardCategory, 
    CASE WHEN `Insight ID` = '...' THEN NULL ELSE `Insight ID` END AS InsightID,
    TIMESTAMP_DIFF(Resolved, Created, MINUTE) AS `Leadtime_mins`,
    TIMESTAMP_DIFF(Resolved, Created, MINUTE)/60 AS `Leadtime_hrs`,
    TIMESTAMP_DIFF(Resolved, Created, MINUTE)/60/24 AS `Leadtime_days`,
    CASE
        WHEN (EXTRACT(YEAR FROM Resolved) - EXTRACT(YEAR FROM Created)) * 12 + (EXTRACT(MONTH FROM Resolved) - EXTRACT(MONTH FROM Created)) > 0 THEN 
             CAST((EXTRACT(YEAR FROM Resolved) - EXTRACT(YEAR FROM Created)) * 12 + (EXTRACT(MONTH FROM Resolved) - EXTRACT(MONTH FROM Created)) AS STRING) || ' months'
        WHEN DATE_DIFF(Resolved, Created, DAY) >= 7 THEN CAST(FLOOR(DATE_DIFF(Resolved, Created, DAY) / 7.0) AS BIGNUMERIC) || ' weeks' 
        WHEN DATE_DIFF(Resolved, Created, DAY) > 0 THEN CAST(DATE_DIFF(Resolved, Created, DAY) AS BIGNUMERIC) || ' days'
        WHEN DATE_DIFF(Resolved, Created, HOUR) > 0 THEN CAST(DATE_DIFF(Resolved, Created, HOUR) AS BIGNUMERIC) || ' hours'
        ELSE CAST(DATE_DIFF(Resolved, Created, MINUTE) AS BIGNUMERIC) || ' minutes'
    END AS LeadTime_auto,
    CASE WHEN RemedyUser.FullName IS NULL THEN Assignee ELSE RemedyUser.FullName END AS AssigneeFullName, 
    CASE WHEN ReporterUser.FullName IS NULL THEN Reporter ELSE ReporterUser.FullName END AS ReporterFullName,
    CASE WHEN CreatorUser.FullName IS NULL THEN Creator ELSE CreatorUser.FullName END AS CreatorFullName,
    CASE WHEN CreatorUser.FullName IS NULL THEN NULL ELSE `Key` END AS JIRACreation,
    CASE WHEN RemedyUser.FullName IS NULL THEN NULL ELSE `Key` END AS JIRAClosure
     

FROM `pccw-internal-virt-agent-uat.JIRAProjects.CCPROV`
LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS RemedyUser ON Assignee = RemedyUser.jiraID
LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS ReporterUser ON Reporter = ReporterUser.jiraID 
LEFT JOIN `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS CreatorUser ON Creator = CreatorUser.jiraID; 
