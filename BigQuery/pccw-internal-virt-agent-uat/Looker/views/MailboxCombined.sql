SELECT *
FROM (
    SELECT 
        *,
        'vasnoc@consoleconnect.com' AS mailbox,
        CASE 
            WHEN sender LIKE '%@consoleconnect.com>%' THEN '@consoleconnect.com'
            WHEN sender LIKE '%@pccwglobal.com%' THEN '@pccwglobal.com'
            WHEN sender LIKE '%@pccw.com%' THEN '@pccw.com'
            WHEN sender LIKE '%noreply@%' OR sender LIKE '%no-reply%' THEN 
                CASE
                    WHEN LOWER(subject) LIKE 'netcool%' THEN 'Automated Notifications'
                    WHEN LOWER(subject) LIKE 'mrsping%' THEN 'Automated Notifications'
                    WHEN LOWER(subject) LIKE 'console loa%' THEN 'Automated Notifications'
                    ELSE 'noreply (auto emails)'
                END
            ELSE 'Customer/Vendor'
        END AS sender_category1,
        CASE 
            WHEN sender LIKE '%support@consoleconnect.com%' THEN 'support@consoleconnect.com'
            WHEN sender LIKE '%ccsupport@consoleconnect.com%' THEN 'ccsupport@consoleconnect.com'
            WHEN sender LIKE '%gsocph@consoleconnect.com%' THEN 'gsocph@consoleconnect.com'
            WHEN sender LIKE '%@pccw.com%' THEN '@pccw.com'
            WHEN sender LIKE '%it-helpdesk@consoleconnect.com%' THEN 'IT-Helpdesk'
            WHEN sender LIKE '%itops@consoleconnect.com%' THEN 'IT-Ops'
            WHEN sender LIKE '%noreply@%' OR sender LIKE '%no-reply%' THEN 
                CASE
                    WHEN LOWER(subject) LIKE '%netcool%' THEN 'Netcool'
                    WHEN LOWER(subject) LIKE '%mrsping%' THEN 'MRSPING'
                    WHEN LOWER(subject) LIKE '%console loa%' THEN 'Console LOA'
                    ELSE 'noreply (auto emails)'
                END
            ELSE
                REGEXP_REPLACE(REGEXP_EXTRACT(sender, r'@(.*)'), r'>$', '')  
        END AS sender_category2
    FROM `pccw-internal-virt-agent-uat.RemedyICS.VASNOCMailbox`

    UNION ALL 

    SELECT 
        *,
        'gsocph@consoleconnect.com' AS mailbox,
        CASE 
            WHEN sender LIKE '%@consoleconnect.com%' THEN '@consoleconnect.com'
            WHEN sender LIKE '%@pccwglobal.com%' THEN '@pccwglobal.com'
            WHEN sender LIKE '%@pccw.com%' THEN '@pccw.com'
            WHEN sender LIKE '%@googlemail.com%' OR sender LIKE '%postmaster@%' THEN 'Mail Failure'
            WHEN LOWER(sender) LIKE '%notification%' OR LOWER(sender) LIKE '%automation%' THEN 'Automated Notifications'
            WHEN LOWER(sender) LIKE '%noreply@%' OR LOWER(sender) LIKE '%no-reply%'OR LOWER(sender) LIKE '%do-not-reply%'  THEN 'Automated Notifications'
            ELSE 'Customer/Vendor'
        END AS sender_category1,
        CASE 
            WHEN sender LIKE '%support@consoleconnect.com%' THEN 'support@consoleconnect.com'
            WHEN sender LIKE '%ccsupport@consoleconnect.com%' THEN 'ccsupport@consoleconnect.com'
            WHEN sender LIKE '%gsocph@consoleconnect.com%' THEN 'gsocph@consoleconnect.com'
            WHEN sender LIKE '%@pccw.com%' THEN '@pccw.com'
            WHEN sender LIKE '%it-helpdesk@consoleconnect.com%' THEN 'IT-Helpdesk'
            WHEN sender LIKE '%itops@consoleconnect.com%' THEN 'IT-Ops'
            WHEN sender LIKE '%noreply@%' OR sender LIKE '%no-reply%' THEN 
                CASE
                    WHEN LOWER(subject) LIKE '%netcool%' THEN 'Netcool'
                    WHEN LOWER(subject) LIKE '%mrsping%' THEN 'MRSPING'
                    WHEN LOWER(subject) LIKE '%console loa%' THEN 'Console LOA'
                    ELSE 'noreply (auto emails)'
                END
            ELSE
                REGEXP_REPLACE(REGEXP_EXTRACT(sender, r'@(.*)'), r'>$', '')  
        END AS sender_category2
    FROM `pccw-internal-virt-agent-uat.RemedyICS.GSOCPHMailbox`

    UNION ALL

    SELECT 
        *,
        'support@consoleconnect.com' AS mailbox,
        CASE 
            WHEN sender LIKE '%@consoleconnect.com>%' THEN '@consoleconnect.com'
            WHEN sender LIKE '%noreply@%' OR sender LIKE '%no-reply%' THEN 
                CASE
                    WHEN LOWER(subject) LIKE 'netcool%' THEN 'Automated Notifications'
                    WHEN LOWER(subject) LIKE 'mrsping%' THEN 'Automated Notifications'
                    WHEN LOWER(subject) LIKE 'console loa%' THEN 'Automated Notifications'
                    ELSE 'noreply (auto emails)'
                END
            ELSE 'Customer/Vendor'
        END AS sender_category1,
        CASE 
            WHEN sender LIKE '%support@consoleconnect.com%' THEN 'support@consoleconnect.com'
            WHEN sender LIKE '%ccsupport@consoleconnect.com%' THEN 'ccsupport@consoleconnect.com'
            WHEN sender LIKE '%gsocph@consoleconnect.com%' THEN 'gsocph@consoleconnect.com'
            WHEN sender LIKE '%it-helpdesk@consoleconnect.com%' THEN 'IT-Helpdesk'
            WHEN sender LIKE '%itops@consoleconnect.com%' THEN 'IT-Ops'
            WHEN sender LIKE '%noreply@%' OR sender LIKE '%no-reply%' THEN 
                CASE
                    WHEN LOWER(subject) LIKE '%netcool%' THEN 'Netcool'
                    WHEN LOWER(subject) LIKE '%mrsping%' THEN 'MRSPING'
                    WHEN LOWER(subject) LIKE '%console loa%' THEN 'Console LOA'
                    ELSE 'noreply (auto emails)'
                END
            ELSE
                REGEXP_REPLACE(REGEXP_EXTRACT(sender, r'@(.*)'), r'>$', '')  
        END AS sender_category2
    FROM `pccw-internal-virt-agent-uat.RemedyICS.SupportMailbox`
)
