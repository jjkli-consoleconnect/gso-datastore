SELECT
    `Request ID`,
    `Submitter`,
    `Original Request ID` AS `IncidentNumber`,
    `Create Date`,
    `Assigned To`,
    `Audit Date`,
    `Last Modified By`,
    `Modified Date`,
    `Action`,
    `Status`,
    `User`,
    `Short Description`,
    `Fields Changed`,
    `Form Name`,
    `GUID Field`,
    `Log`
FROM `HPD:HelpDesk_AuditLogSystem` 
LIMIT 1