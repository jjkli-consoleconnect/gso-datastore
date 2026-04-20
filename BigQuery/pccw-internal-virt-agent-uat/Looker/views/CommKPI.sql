SELECT 
    wl.`IncidentNumber` AS IncidentNumber,
    wl.`WorkLogType` AS `WorkLogType`,
    wl.`WorkLogSubmitDate` AS `WorkLogSubmitDate`,
    wl.`DescriptionFullName` AS `FullName`,
    hd.`Assigned_Group` AS NOC,
    hd.`GCSC_1st_Customer_Update` AS `FirstRT`,
    hd.`GCSC_2nd_Customer_Update` AS `SecondRT`,
    hd.`GCSC_3rd_Customer_Update` AS `ThirdRT`,
    CASE WHEN `GCSC_1st_Customer_Update` = `WorkLogSubmitDate` THEN `Initial_Response_Time` ELSE NULL END AS `FirstResponse`,
    CASE WHEN `GCSC_2nd_Customer_Update` = `WorkLogSubmitDate` THEN `Second_Response_Time` ELSE NULL END AS `SecondResponse`,
    CASE WHEN `GCSC_3rd_Customer_Update` = `WorkLogSubmitDate` THEN `Third_Response_Time` ELSE NULL END AS `ThirdResponse`,
    wl.`CustCommKeywords`,
    wl.`DetailedDescription`,
    CASE 
        WHEN `GCSC_1st_Customer_Update` IS NULL THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `1st_KPI_Null`,
    CASE 
        WHEN `Initial_Response_Time` > 30 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `1st_KPI_Fail`,
    CASE 
        WHEN `GCSC_1st_Customer_Update` = `WorkLogSubmitDate` AND `Initial_Response_Time` <= 30 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `1st_KPI_Achieved`,
    CASE 
        WHEN `GCSC_2nd_Customer_Update` IS NULL THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `2nd_KPI_Null`,
    CASE 
        WHEN `Second_Response_Time` > 120 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `2nd_KPI_Fail`,
    CASE 
        WHEN `GCSC_2nd_Customer_Update` = `WorkLogSubmitDate` AND `Second_Response_Time` <= 120 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `2nd_KPI_Achieved`,
    CASE 
        WHEN `GCSC_3rd_Customer_Update` IS NULL THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `3rd_KPI_Null`,
    CASE 
        WHEN `Third_Response_Time` > 210 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `3rd_KPI_Fail`,
    CASE 
        WHEN `GCSC_3rd_Customer_Update` = `WorkLogSubmitDate` AND `Third_Response_Time` <= 210 THEN wl.`IncidentNumber`
        ELSE NULL
    END AS `3rd_KPI_Achieved`




FROM `pccw-internal-virt-agent-uat.Looker.WorkLog` wl
LEFT JOIN `pccw-internal-virt-agent-uat.Looker.helpdesk` hd 
    ON wl.`IncidentNumber` = hd.`Incident_Number`        

WHERE 
    hd.`Status` = 'Closed'
    AND hd.`CaseType` = 'Incident'
    AND wl.`WorkLogType`= 'Email-Progress Update'
    AND (wl.WorkLogSubmitDate <= hd.GCSC_3rd_Customer_Update OR hd.GCSC_3rd_Customer_Update IS NULL)

ORDER BY WorkLogSubmitDate DESC
