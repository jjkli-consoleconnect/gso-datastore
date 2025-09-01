Sheet1 → BigQuery

What this folder contains
- `Code.gs` — Apps Script that reads `Sheet1` from the active spreadsheet, creates a BigQuery table (if missing) with STRING fields derived from the header row, and inserts data in batches.
- `appsscript.json` — manifest enabling the BigQuery advanced service and required OAuth scopes.

Quick setup
1. Open the spreadsheet you want to import from, then open Extensions → Apps Script.
2. Create a new project (or use a bound project). Copy `Code.gs` contents into the editor and save.
3. In the Apps Script editor go to: Services (left sidebar) → Add a service → select "BigQuery API" and add it. (Or: Resources → Advanced Google services → enable BigQuery.)
4. In Google Cloud Console, make sure the project linked to the Apps Script has BigQuery API enabled.
5. Edit the top of `Code.gs` and set `PROJECT_ID`, `DATASET_ID`, and `TABLE_ID`.
6. Run `importSheet1ToBigQuery()` manually once to authorize and test.
7. To schedule weekly runs, run `createWeeklyTrigger()` once and customize the weekday/time in that function if desired.

Notes
- All sheet columns are stored as STRING in BigQuery to keep schema simple. Modify `ensureTableExists()` if you want typed fields.
- For very large datasets (>100k rows) consider exporting to Cloud Storage and using a load job for efficiency.
 
SQL: CREATE TABLE and MERGE example

If you prefer to create the target table manually, here's a BigQuery DDL using the sheet columns you provided. All fields are STRING; adjust types as needed.

```sql
CREATE TABLE `pccw-internal-virt-agent-uat.GSO.Staff` (
	Sheet1 → BigQuery

	What this folder contains
	- `Code.gs` — Apps Script that reads `Sheet1` from the active spreadsheet, creates a BigQuery table (if missing) with STRING fields derived from the header row, and inserts data in batches. The script now uses a temp table + MERGE pattern and can optionally set an ingestion timestamp.
	- `appsscript.json` — manifest enabling the BigQuery advanced service and required OAuth scopes.

	Quick setup
	1. Open the spreadsheet you want to import from, then open Extensions → Apps Script.
	2. Create a new project (or use a bound project). Copy `Code.gs` contents into the editor and save.
	3. In the Apps Script editor go to: Services (left sidebar) → Add a service → select "BigQuery API" and add it. (Or: Resources → Advanced Google services → enable BigQuery.)
	4. In Google Cloud Console, make sure the project linked to the Apps Script has BigQuery API enabled.
	5. Edit the top of `Code.gs` and set `PROJECT_ID`, `DATASET_ID`, `TABLE_ID`, and `KEY_COLUMN`.
	6. Run `importSheet1ToBigQuery()` manually once to authorize and test.
	7. To schedule weekly runs, run `createWeeklyTrigger()` once and customize the weekday/time in that function if desired.

	Notes
	- All sheet columns are stored as STRING in BigQuery to keep schema simple. Modify `ensureTableExists()` if you want typed fields.
	- For very large datasets (>100k rows) consider exporting to Cloud Storage and using a load job for efficiency.

	SQL: CREATE TABLE and MERGE example

	If you prefer to create the target table manually, here's a BigQuery DDL using the sheet columns you provided. The script supports an optional `ingestion_time` TIMESTAMP; include it if you set `USE_INGESTION_TIMESTAMP = true` in `Code.gs`.

	Simple (all STRING columns)

	```sql
	CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.Staff` (
		staff_id_number STRING,
		staff_name       STRING,
		team_name        STRING,
		team_head        STRING,
		sub_team         STRING,
		country          STRING,
		title            STRING,
		remark           STRING
	);
	```

	With optional ingestion timestamp and clustering by key

	```sql
	CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.GSO.Staff` (
		staff_id_number STRING,
		staff_name       STRING,
		team_name        STRING,
		team_head        STRING,
		sub_team         STRING,
		country          STRING,
		title            STRING,
		remark           STRING,
		ingestion_time   TIMESTAMP OPTIONS (description = "Timestamp when row was imported")
	)
	CLUSTER BY (staff_id_number);
	```

	Recommended MERGE pattern (the Apps Script creates a temp table, loads it, then runs a MERGE):

	```sql
	MERGE `pccw-internal-virt-agent-uat.GSO.Staff` T
	USING `pccw-internal-virt-agent-uat.GSO.Staff_tmp_<uuid>` S
	ON T.staff_id_number = S.staff_id_number
	WHEN MATCHED THEN
		UPDATE SET
			staff_name = S.staff_name,
			team_name = S.team_name,
			team_head = S.team_head,
			sub_team = S.sub_team,
			country = S.country,
			title = S.title,
			remark = S.remark,
			ingestion_time = CURRENT_TIMESTAMP()
	WHEN NOT MATCHED THEN
		INSERT (staff_id_number, staff_name, team_name, team_head, sub_team, country, title, remark, ingestion_time)
		VALUES (S.staff_id_number, S.staff_name, S.team_name, S.team_head, S.sub_team, S.country, S.title, S.remark, CURRENT_TIMESTAMP());
	```

	Notes:
	- The script adds a temporary column `_load_uuid` to help trace which rows belonged to a single run. The MERGE SQL excludes it.
	- The Apps Script will create a temp table named like `Staff_tmp_<uuid>` and delete it after the MERGE (best-effort).
