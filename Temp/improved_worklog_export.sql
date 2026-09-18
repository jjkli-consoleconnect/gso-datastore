-- Improved WorkLog export query for the BMC Helix dashboard (drop-in replacement).
--
-- IMPORTANT dialect note: BMC Helix Dashboards translate Service-Management
-- queries through the ARJDBC layer, which only supports a fixed function list
-- (Character Index/Position = CHARINDEX, Replace String = REPLACE, SubString,
-- LENGTH, CASE WHEN, ...). Functions like CHAR() and REGEXP_REPLACE are NOT
-- supported and cause "Failed to parse SQL" errors. This query uses only
-- documented ARJDBC functions.
--
-- Changes vs. the original:
--   1. Double quotes are removed from the description. Unescaped quotes in the
--      free-text description intermittently corrupt the exported CSV's quoting
--      (observed since 2026-09-15 as 'Header contract violation' /
--      'Row width mismatch' import failures downstream).
--   2. The '---' / 'wrote:' extraction is guarded: when either marker is missing
--      the original SUBSTR produced garbage (negative offsets / whole blob);
--      now it falls back to the sanitized description instead.
--   3. Additional notification-noise filter ('%This is Email%').
--
-- Version A below is the conservative, fully dialect-safe version (only removes
-- quote characters). Version B additionally collapses line breaks, using string
-- literals that contain a real CR and LF character between the quotes -- try it
-- only if Version A parses and works, since literal control characters inside
-- quoted strings may or may not survive the ARJDBC translator.

-- =========================== VERSION A (safe) ===========================

SELECT
  wl.`Incident Number`        AS IncidentNumber,
  wl.`Work Log Type`          AS WorkLogType,
  wl.`Work Log ID`            AS WorkLogID,
  wl.`Work Log Submit Date`   AS WorkLogSubmitDate,
  CASE
    WHEN cp_sub.`Full Name` IS NOT NULL THEN cp_sub.`Full Name`
    ELSE wl.`Work Log Submitter`
  END                         AS WorkLogSubmitter,
  wl.`Last Modified Date`     AS LastModifiedDate,
  CASE
    WHEN cp_mod.`Full Name` IS NOT NULL THEN cp_mod.`Full Name`
    ELSE wl.`Last Modified By`
  END                         AS LastModifiedBy,
  CASE
    WHEN CHARINDEX('---', REPLACE(wl.`Detailed Description`, '"', '')) > 0
         AND CHARINDEX('wrote:', REPLACE(wl.`Detailed Description`, '"', ''),
                       CHARINDEX('---', REPLACE(wl.`Detailed Description`, '"', '')) + 3) > 0
      THEN SUBSTR(
             REPLACE(wl.`Detailed Description`, '"', ''),
             CHARINDEX('---', REPLACE(wl.`Detailed Description`, '"', '')) + 3,
             CHARINDEX('wrote:', REPLACE(wl.`Detailed Description`, '"', ''),
                       CHARINDEX('---', REPLACE(wl.`Detailed Description`, '"', '')) + 3)
               - CHARINDEX('---', REPLACE(wl.`Detailed Description`, '"', '')) - 3
           )
    ELSE REPLACE(wl.`Detailed Description`, '"', '')
  END                         AS ExtractedDescription

FROM `HPD:WorkLog` wl
LEFT JOIN `HPD:Help Desk` hd  ON wl.`Incident Number` = hd.`Incident Number`
LEFT JOIN `CTM:People` cp_sub ON wl.`Work Log Submitter` = cp_sub.`Remedy Login ID`
LEFT JOIN `CTM:People` cp_mod ON wl.`Last Modified By` = cp_mod.`Remedy Login ID`

WHERE wl.`Last Modified Date` BETWEEN $__from/1000 AND $__to/1000
  AND hd.`Assigned Group` IN ($assignedgroup)
  AND wl.`Work Log Type` NOT IN ('Assignment Change', '---NOC Selection---', 'Internal Escalation')
  AND wl.`Detailed Description` NOT LIKE 'Ticket Escalated Notification%'
  AND wl.`Detailed Description` NOT LIKE 'Escalated to Manager%'
  AND wl.`Detailed Description` NOT LIKE 'Ticket Creation Notification%'
  AND wl.`Detailed Description` NOT LIKE 'Ticket Closure Notification%'
  AND wl.`Detailed Description` NOT LIKE '%This is Email%'

ORDER BY WorkLogSubmitDate DESC

-- =========================== VERSION B (full) ===========================
-- Identical to Version A except each REPLACE(wl.`Detailed Description`, '"', '')
-- becomes the nested form below, which also collapses CR and LF to spaces.
-- The quoted strings in the middle contain one real CR (or LF) character each,
-- so the expression looks split across lines -- that is intentional.
--
--   REPLACE(REPLACE(REPLACE(wl.`Detailed Description`, '"', ''), '
-- ', ' '), '
-- ', ' ')
--
-- To use Version B: replace every occurrence of
--   REPLACE(wl.`Detailed Description`, '"', '')
-- in Version A with the nested expression above. If the dashboard rejects it,
-- stay on Version A.
