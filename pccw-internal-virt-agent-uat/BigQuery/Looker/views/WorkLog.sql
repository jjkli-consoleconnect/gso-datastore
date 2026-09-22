WITH DescriptionPart AS (
    SELECT
        wl.`IncidentNumber`,
        wl.`WorkLogSubmitDate`,
        wl.`LastModifiedDate`,
        wl.`WorkLogSubmitter`,
        wl.`EffortTimeSpent_mins`,
        wl.`WorkLogType`,
        wl.`DetailedDescription`,
        COALESCE(usr_submitter.FullName, wl.`WorkLogSubmitter`) AS WorkLogSubmitterFullName,
        COALESCE(usr_modified.FullName, wl.`LastModifiedBy`) AS LastModifiedByFullName,
        CASE
            WHEN REGEXP_CONTAINS(wl.`DetailedDescription`, r'---') THEN
                SUBSTR(wl.`DetailedDescription`, STRPOS(wl.`DetailedDescription`, '---') + 3)
            ELSE ''
        END AS RelevantDescription,
        CASE
            WHEN wl.`WorkLogType` = 'Internal Work Log (Email)' AND wl.`WorkLogSubmitter` = 'AR_ESCALATOR' AND REGEXP_CONTAINS(wl.`DetailedDescription`, r'---') AND REGEXP_CONTAINS(wl.`DetailedDescription`, r'wrote:') THEN
                REPLACE(
                    REPLACE(  
                        REPLACE(  
                            REGEXP_REPLACE(  
                                SUBSTR(
                                    wl.`DetailedDescription`,
                                    STRPOS(wl.`DetailedDescription`, '---') + 3,
                                    GREATEST(
                                        STRPOS(wl.`DetailedDescription`, 'wrote:') - (STRPOS(wl.`DetailedDescription`, '---') + 3),
                                        0
                                    )
                                ),
                                '[^[:print:]]',  
                                ''
                            ),
                            '\r\n',  
                            '\n'
                        ),
                        '\r',    
                        '\n'
                    ),
                    '\n',      
                    '<br>'
                )
            ELSE
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REGEXP_REPLACE(  
                                wl.`DetailedDescription`,
                                '[^[:print:]]',  
                                ''
                            ),
                            '\r\n',
                            '\n'
                        ),
                        '\r',
                        '\n'
                    ),
                    '\n',
                    '<br>'
                )
        END AS ExtractedDescription
    FROM
        `pccw-internal-virt-agent-uat.RemedyICS.WorkLog` AS wl
    LEFT JOIN
        `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS usr_submitter ON wl.`WorkLogSubmitter` = usr_submitter.InsightID
    LEFT JOIN
        `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS usr_modified ON wl.`LastModifiedBy` = usr_modified.InsightID
)
SELECT
    IncidentNumber,
    WorkLogSubmitDate,
    LastModifiedDate,
    WorkLogSubmitter,
    EffortTimeSpent_mins,
    WorkLogType,
    DetailedDescription,
    WorkLogSubmitterFullName,
    LastModifiedByFullName,
    RelevantDescription,
    CASE
        WHEN REGEXP_CONTAINS(RelevantDescription, r'wrote:') THEN
            COALESCE(nl.FullName, WorkLogSubmitterFullName, WorkLogSubmitter)
        ELSE
            COALESCE(nl.FullName, WorkLogSubmitterFullName, WorkLogSubmitter)
    END AS DescriptionFullName,
    CASE
        WHEN wl.`WorkLogType` = 'Email-Progress Update' AND REGEXP_CONTAINS(LOWER(RelevantDescription), r'check') THEN 'checking'
        WHEN wl.`WorkLogType` = 'Email-Progress Update' AND REGEXP_CONTAINS(LOWER(RelevantDescription), r'acknow') THEN 'acknowledged'
        WHEN wl.`WorkLogType` = 'Email-Progress Update' AND REGEXP_CONTAINS(LOWER(RelevantDescription), r'work|invest|look') THEN 'others'
        ELSE NULL
    END AS CustCommKeywords
FROM
    DescriptionPart AS wl
LEFT JOIN
    `pccw-internal-virt-agent-uat.RemedyICS.UserID` AS nl ON wl.`WorkLogType` = 'Internal Work Log (Email)' AND wl.`WorkLogSubmitter` = 'AR_ESCALATOR' AND REGEXP_CONTAINS(
        ExtractedDescription,  
        r'\b' || nl.EmailSignature || r'\b'
    )

ORDER BY WorkLogSubmitDate DESC
