SELECT 
    hd.`Incident Number` AS IncidentNumber,
    hd.`Status`,
    hd.`Case Type*` AS casetype,
    hd.`Assigned Group`,
    hd.`Categorization Tier 1`,
    hd.`Categorization Tier 2`,
    hd.`Categorization Tier 3`,
    hd.`GCSC 1st Customer Update`,
    hd.`GCSC 2nd Customer Update`,
    hd.`GCSC 3rd Customer Update`,
    hd.`Initial Response Time`,
    hd.`Second Response Time`,
    hd.`Third Response Time`,
    hd.`Prod ID`,
    DBFN('REPLACE', hd.`Fault Cause`, ',', '') AS `Fault Cause`,
    hd.`Closed Date`,
    hd.`Submit Date`,
    DBFN('REPLACE', hd.`Assignee`, ',', '') AS `Assignee`,
    CASE
      WHEN cp_clo."Full Name" IS NOT NULL AND cp_clo."Full Name" <> '' THEN DBFN('REPLACE', cp_clo."Full Name", ',', '')
      WHEN hd."Closed By" IS NOT NULL AND hd."Closed By" <> '' THEN DBFN('REPLACE', hd."Closed By", ',', '')
      ELSE NULL
    END AS ClosedBy,
    CASE
      WHEN cp_sub.`Full Name` IS NOT NULL AND cp_sub.`Full Name` <> '' THEN DBFN('REPLACE', cp_sub.`Full Name`, ',', '')
      WHEN hd.Submitter IS NOT NULL AND hd.Submitter <> '' THEN DBFN('REPLACE', hd.Submitter, ',', '')
      ELSE NULL
    END AS Submitter,
    CASE WHEN hd.`MTTR Manual (min)` > 0 THEN hd.`MTTR Manual (min)` ELSE hd.`MTTR (min)` END AS `True MTTR_mins`,
    hd.`Cust ID`,
    CASE
        WHEN hd.`Carrier` IS NULL THEN NULL
        ELSE '"' + DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', hd.`Carrier`, '\r\n', ''), '\r', ''), '\n', ''), '"', '') + '"'
      END AS Carrier,
    CASE
        WHEN hd.`Customer Name` IS NULL THEN NULL
        ELSE '"' + DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', hd.`Customer Name`, '\r\n', ''), '\r', ''), '\n', ''), '"', '') + '"'
      END AS `Customer Name`,
    CASE
        WHEN hd.`SR No.+` IS NULL THEN NULL
        ELSE '"' + DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', UPPER(hd.`SR No.+`), '\r\n', ''), '\r', ''), '\n', ''), '"', '') + '"'
      END AS SRNo,
    hd.`Last Resolved Date` AS LastResolvedDate, 
    hd.`Reported Date` AS ReportedDate, 
    hd.`Responded Date` AS RespondedDate, 
    CASE
        WHEN hd.`Fault Cause Detail` IS NULL THEN NULL
        ELSE '"' + DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', hd.`Fault Cause Detail`, '|', ''), '\r\n', ''), '\r', ''), '\n', ''), '"', '') + '"'
    END AS `FaultCauseDetail`,
      hd.`Last Modified Date` AS LastModifiedDate,
      hd.`Reported By*` AS ReportedBy,
    shr.`Product Family`,
    CASE WHEN shr.`Product Family` IS NULL 
      THEN NULL 
      ELSE shr.`Product ID` + ' - ' + shr.`PROD DESC`
    END AS `ProductDescription`,
    hd.`GSMP Circuit ID`,
    hd.`Priority`,
    hd.`Urgency`

FROM 
    `HPD:Help Desk` hd
LEFT JOIN 
    `CTM:People` cp_sub ON hd.`Submitter` = cp_sub.`Remedy Login ID`
LEFT JOIN 
    `CTM:People` cp_clo ON hd.`Closed By` = cp_clo.`Remedy Login ID`
LEFT JOIN
    `SHR:People` shr ON hd.`SR No.+` = shr.`Login Name`

WHERE 
    hd.`Incident Number` IN ('INC000010557712', 'INC000010477532', 'INC000010583928', 'INC000010585276', 'INC000010609800', 'INC000010625234', 'INC000010617751', 'INC000010657283', 'INC000010612078', 'INC000010578786')

ORDER BY 
    hd.`Last Modified Date` DESC


