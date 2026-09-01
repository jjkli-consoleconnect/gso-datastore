SELECT 
    wt.NOC,
    wt.Date,
    wt.Tool,
    wt.Usage,
    u.fullname AS Fullname
FROM
    `pccw-internal-virt-agent-uat.RemedyICS.WebtoolUsage` AS wt
LEFT JOIN 
    `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS u ON wt.user = u.insightID

WHERE Fullname IS NOT NULL
