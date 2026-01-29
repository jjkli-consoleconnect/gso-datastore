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
═══════════════════════════════════════════════════════════════════════════════

=== SESSION UPDATE - 29 Jan 2026 ===

STATUS: COMPLETED & DEPLOYED ✓

WHAT HAPPENED:
Operations team provided shift times for 11 NOCs:
- GSOC TX - HK: 08-14 (Morning), 14-23 (Afternoon), 23-08 (Evening)
- HKNOC: 08-16 (Morning), 16-23 (Afternoon), 23-08 (Evening)
- GSOC TX - PH: 07-15 (Morning), 15-23 (Afternoon), 23-07 (Evening)
- FMC: 08-14 (Morning), 14-23 (Afternoon), 23-08 (Evening)
- SES: 08-17 (Morning), 17-00 (Afternoon), 00-08 (Evening)
- Console Connect: 07-15 (Morning), 15-23 (Afternoon), 23-07 (Evening)
- VAS NOC: 07-15 (Morning), 15-23 (Afternoon), 23-07 (Evening)
- GSOC: 08-14 (Morning), 14-23 (Afternoon), 23-08 (Evening)
- PHSOC: 07-15 (Morning), 15-23 (Afternoon), 23-07 (Evening)
- ICX: 08-14 (Morning), 14-23 (Afternoon), 23-08 (Evening)

NOCs without defined shifts (set to NULL, filtered out):
- Planned Event Mgt
- USNOC
- Soft Switch Management
- Bel NOC

IMPLEMENTATION:
1. Created shift_config CTE with all 11 NOCs and their 3 shifts each (28 total STRUCT entries)
2. Implemented midnight-crossing logic for shifts where end_hour < start_hour
3. Added LEFT JOIN shift_config to Creation, Closure, and WorkLog CTEs
4. Updated column names in SELECT to match destination table schema:
   - Shift → ShiftSnapshot
   - Shift_Date → Snapshot_Date
5. Added 2 missing columns to SELECT for table compatibility:
   - Snapshot_Hour: EXTRACT(HOUR FROM CURRENT_TIMESTAMP())
   - Snapshot_DateTime: CURRENT_DATETIME()
6. Added WHERE clause to filter: base_events.Shift IS NOT NULL

DEPLOYMENT:
- SQL deployed to all 24 hourly scheduled queries (00-23) via patch_transfer.py
- Used BigQuery Data Transfer Service API with DataTransferServiceClient
- All 24 queries updated successfully

TESTING:
- Test query validation: 611 rows returned, structure verified ✓
- Manual trigger of query 05: Successfully wrote 614 rows to destination table ✓
- Destination table now contains: pccw-internal-virt-agent-uat.GSO.CenterOperationsShiftSnapshotsAgg
- Latest data date: 2026-01-29

KEY CODE PATTERNS USED:
- Midnight-crossing shift logic: (sc.end_hour > sc.start_hour AND hour >= start AND hour < end) OR (sc.end_hour < sc.start_hour AND (hour >= start OR hour < end))
- Shift name standardization: 1 Morning, 2 Afternoon, 3 Evening (for sorting)
- COALESCE for actor name: Creation > Closure > WorkLog > Assignee
- STRING_AGG for field aggregation with comma/newline separators

DESTINATION TABLE SCHEMA (20 columns):
1. Actor_FullName: STRING
2. NOC: STRING
3. CaseType: STRING
4. Status: STRING
5. ShiftSnapshot: STRING (format: "YYYY-MM-DD - N ShiftName")
6. Snapshot_Date: DATE
7. Snapshot_Timestamp: TIMESTAMP
8. DoW: STRING (day of week)
9. WorkLog_Count: INTEGER
10. Creation_Count: INTEGER
11. Closure_Count: INTEGER
12. WorkLog_Distinct: INTEGER
13. Creation_Tickets: INTEGER
14. Closure_Tickets: INTEGER
15. Tickets_Supported: INTEGER
16. Tickets_List: STRING
17. Ticket_Details: STRING
18. EffortDetails: STRING
19. Snapshot_Hour: INTEGER
20. Snapshot_DateTime: DATETIME

CLUSTERING APPLIED:
Table pccw-internal-virt-agent-uat.GSO.CenterOperationsShiftSnapshotsAgg clustered on:
- Snapshot_Date
- NOC
- ShiftSnapshot
- Actor_FullName

TROUBLESHOOTING NOTES FOR FUTURE REFERENCE:
- Initial issue: Table was empty despite successful scheduled query updates
  Solution: Realized queries weren't using INSERT INTO, relying on destination_table_name_template parameter
- Column count mismatch: Query returned 18 columns but table has 20
  Solution: Added Snapshot_Hour and Snapshot_DateTime columns
- Query attempted as INSERT INTO with write_disposition caused "DDL/DML with partitioning not supported" error
  Solution: Reverted to original SELECT-based approach with destination_table_name_template parameter

FILES MODIFIED:
- g:\My Drive\Scripts\Temp\CenterOperationsShiftSnapshots_aggregated_scheduled.sql (459 lines)
- g:\My Drive\Scripts\Temp\patch_transfer.py (88 lines, used for deploying to all 24 queries)

SCHEDULED QUERIES UPDATED (24 total):
- CenterOps Hourly Snapshot 00-23 (one query per hour, europe location)
- Project ID: 14417857267
- Destination Dataset: GSO
- Destination Table: CenterOperationsShiftSnapshotsAgg

NEXT TIME SOMEONE NEEDS TO UPDATE THIS:
1. Modify the shift_config CTE in the SQL file
2. Run patch_transfer.py to push changes to all 24 queries atomically
3. Manual trigger a test run: StartManualTransferRunsRequest() via DataTransferServiceClient
4. Verify data in destination table with: SELECT COUNT(*) FROM pccw-internal-virt-agent-uat.GSO.CenterOperationsShiftSnapshotsAgg

═══════════════════════════════════════════════════════════════════════════════