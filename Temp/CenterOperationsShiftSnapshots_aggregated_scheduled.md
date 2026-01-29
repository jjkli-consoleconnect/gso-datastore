=== LOOKER STUDIO SHIFT TIME FILTERING - SESSION SUMMARY ===

Date: 28 Jan 2026
Status: PENDING - Waiting for Operations team response on shift times

═══════════════════════════════════════════════════════════════════════════════

PROBLEM IDENTIFIED:
Your Looker Studio dashboard shows incorrect time ranges when selecting shifts that cross midnight (e.g., 23:00-07:00).
When you select "27 Jan 23:00 to 28 Jan 07:00", the time series chart displays "06:00 to 01:00" instead.

ROOT CAUSE:
- Your current In_Hour_Range calculated field applies hours independently on each date
- This causes the filter to include hours that shouldn't be there (e.g., 27 Jan 00:00-06:00)
- Looker Studio doesn't support window functions in calculated fields, so formulas like MIN(Snapshot_Date) OVER () don't work

CURRENT SETUP:
- SQL Query: g:\My Drive\Scripts\Temp\CenterOperationsShiftSnapshots_aggregated_scheduled.sql
- Data Source: pccw-internal-virt-agent-uat.GSO.CenterOperationsShiftSnapshotsAgg (BigQuery table)
- Filters: Date picker (27 Jan - 28 Jan) + Start Hour (23) + End Hour (7) parameters
- Calculated Field: In_Hour_Range (applied globally, affecting all charts)

═══════════════════════════════════════════════════════════════════════════════

SOLUTION IDENTIFIED:
Hardcode shift times for each team/NOC into the BigQuery SQL query.

WHY THIS WORKS:
- Filtering is done at the data source level (more reliable)
- No dependency on Looker Studio calculated fields
- Handles midnight-crossing shifts correctly
- Each team can have their own shift hours baked in

NEXT STEPS - WAITING FOR:
1. Get confirmation from Operations team on shift times for each NOC/Team
2. Format needed:
   - Team/NOC name (e.g., PHSOC, WNOC, EMEA_NOC)
   - Start hour (0-23)
   - End hour (0-23)
   - Any special cases or notes

EXAMPLE OF EXPECTED DATA FROM OPERATIONS:
   - PHSOC: 23:00 to 07:00 (night shift, crosses midnight)
   - WNOC: 06:00 to 14:00 (morning shift)
   - EMEA_NOC: 14:00 to 22:00 (afternoon shift)

═══════════════════════════════════════════════════════════════════════════════

IMPLEMENTATION PLAN (Once shift times are confirmed):

1. Update the SQL query with a new CASE statement:
   
   CASE
     WHEN e.NOC = 'PHSOC' AND (EXTRACT(HOUR FROM hourly_window.hour_start) >= 23 OR EXTRACT(HOUR FROM hourly_window.hour_start) < 7) THEN 1
     WHEN e.NOC = 'WNOC' AND (EXTRACT(HOUR FROM hourly_window.hour_start) >= 6 AND EXTRACT(HOUR FROM hourly_window.hour_start) < 14) THEN 1
     WHEN e.NOC = 'EMEA_NOC' AND (EXTRACT(HOUR FROM hourly_window.hour_start) >= 14 AND EXTRACT(HOUR FROM hourly_window.hour_start) < 22) THEN 1
     ELSE 0
   END AS In_Team_Shift

2. In Looker Studio:
   - Remove the In_Hour_Range calculated field (or keep it but don't use it)
   - Add a new filter: In_Team_Shift = 1
   - Remove Start Hour and End Hour parameters (if not needed for other use)
   - This will ensure all charts show only the correct shift hours

ALTERNATIVE (If you want to keep flexibility):
   - Add DECLARE @start_hour INT64, @end_hour INT64 parameters to SQL
   - Use parameterized formulas
   - Keep user hour pickers in Looker Studio
   - But this requires a custom query in the data source

═══════════════════════════════════════════════════════════════════════════════

FILES REFERENCED IN THIS SESSION:
- Temp/CenterOperationsShiftSnapshots_aggregated_scheduled.sql (main SQL query)
- Temp/RECOMMENDED_SOLUTION.txt (previous formula attempts)
- Temp/CONTINUOUS_TIME_WINDOW_FIX.txt (advanced attempted solutions)
- Temp/verification_and_debugging.txt (debugging guide)
- Temp/corrected_formula_and_fix.txt (formula analysis)

KEY LEARNINGS:
1. Looker Studio calculated fields don't support window functions
2. Date picker controls don't expose parameters for formulas
3. Hardcoding in SQL is cleaner than trying to solve this in Looker Studio
4. For multi-team scenarios with different shifts, a lookup table or CASE statement in SQL is best practice

═══════════════════════════════════════════════════════════════════════════════

WHEN OPERATIONS TEAM RESPONDS:
1. Collect the shift times for each team/NOC
2. Come back to this file
3. I'll generate the exact SQL code to add to your query
4. Deploy and test in Looker Studio

Contact: Operations team (waiting for shift time details)
