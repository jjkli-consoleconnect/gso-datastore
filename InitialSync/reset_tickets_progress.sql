-- Reset JiraTickets_progress table to start fresh
-- This deletes all failed/degraded windows so the script can create new ones with current data

-- Option 1: Delete ALL progress (fresh start)
-- DELETE FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets_progress` WHERE TRUE;

-- Option 2: Delete only failed/degraded windows (keeps completed history)
DELETE FROM `pccw-internal-virt-agent-uat.GSO.JiraTickets_progress` 
WHERE Status IN ('failed', 'degraded');

-- Option 3: Update one project to test with today's window
-- UPDATE `pccw-internal-virt-agent-uat.GSO.JiraTickets_progress`
-- SET 
--   WindowStart = TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR),
--   WindowEnd = CURRENT_TIMESTAMP(),
--   Status = 'in_progress',
--   RowCount = NULL
-- WHERE Project = 'TAC'
-- AND Status IN ('failed', 'degraded')
-- ORDER BY WindowStart DESC
-- LIMIT 1;
