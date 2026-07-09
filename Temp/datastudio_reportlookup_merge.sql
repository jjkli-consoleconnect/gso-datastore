CREATE TEMP TABLE src AS
SELECT * FROM UNNEST([
  STRUCT('9c6df021-a4f5-4a22-b214-24df6786ed2c' AS looker_studio_report_id, '[M] CCAS' AS report_name),
  STRUCT('51396e3f-d6c9-47e3-8068-7d060e05b5ee', 'Datapipe Monitor'),
  STRUCT('e0887814-9c25-4e27-9804-7d129176f799', 'Wanda Performance - Usage Report'),
  STRUCT('85fe649b-79d3-4a70-b81d-97f4601c4852', 'IT Operations Dashboard'),
  STRUCT('9ac51e81-6d74-41a1-bbf5-50ac5e3db431', 'Wanda Performance - Private'),
  STRUCT('ce1ec6c6-2662-4aa8-bdb5-4e93f84e41ba', 'Cost Gap Report'),
  STRUCT('a9b0533f-558f-4a0c-b50e-496ce8980404', 'Customer Success Management'),
  STRUCT('fa541938-eb12-438c-be10-3f7a0b7178a4', 'GSO Performance Dashboard'),
  STRUCT('e8f9ee42-6e4a-48ef-a410-9a3ddb8d1c0b', 'Center Operations'),
  STRUCT('5610afb9-4c67-4ab4-a8d0-b0c7d356b0f5', 'IT Helpdesk Dashboard'),
  STRUCT('205c1245-c372-4b47-8e5e-1e6404dc964c', 'Untitled Report'),
  STRUCT('1b0d1e50-7f83-4ccb-8b76-4ccc43d2ffd3', 'Wanda Performance Monitor'),
  STRUCT('e339c739-c6f3-43bb-9248-22d7849171b6', 'GS&O Automation and Analytics - Jira Projects Report'),
  STRUCT('e2cb0490-16ef-48ee-a0a3-9df22447f81a', 'AI Lab ✨'),
  STRUCT('6ed5d631-0161-4fbb-86ca-4c00d7d3b202', 'Wanda - KMS Agent Consumption Dashboard'),
  STRUCT('35e20a26-3520-41e3-a162-fe533152b72a', 'ARCHIVED - Wanda Performance'),
  STRUCT('ccfc0acd-04e4-4124-b7cc-3b6dca5f3cc8', 'Cost Tracking Dashboard_FOCUS [Ver 2.0] - WIP'),
  STRUCT('b810b887-cae2-47ca-a946-27eee52d4e2e', 'Untitled Report'),
  STRUCT('9dbf3a3a-550c-41f4-a2e7-d0b025ecf756', 'Vendor/Carrier Performance'),
  STRUCT('8dff4338-309c-4686-9458-c063ab1cc059', 'Knowledge Ingestion Monitoring Dashboard - New'),
  STRUCT('c0833ea1-66fc-429e-8112-784f4f044dd3', '[Wireframe: DONT Consume the data]: Cost Gap Dashboard'),
  STRUCT('960560a9-713d-480c-83de-f2ed4df4dcf7', 'Vendor Verification Management'),
  STRUCT('f4fbae40-330f-4709-bac2-2893b5211a18', 'ARCHIVE - QMS - Quality Objectives'),
  STRUCT('54bc8cf7-50e0-4d9a-bdd3-c69cb4c0a738', '[M] SRE Month End Report'),
  STRUCT('4d0c5177-bcba-433b-9c18-9c72a9b1ef05', 'Managed Security Services'),
  STRUCT('85a63c13-7d91-4adb-8e1c-a56e4ce64689', 'ARCHIVE - Cost Item Expiration'),
  STRUCT('2783d850-f43f-4903-bd3d-eb0c468996e6', 'GS&O Customer Profile Performance'),
  STRUCT('26df6ff9-b957-416f-b96e-74fb4155cab1', 'Agile Ops'),
  STRUCT('b3f8fa33-a40b-4e56-91bc-3e2b9025a82c', 'Submarine Cable Event'),
  STRUCT('c16e168c-1597-460c-b67e-45eb788c6053', 'ICS Customer Centric'),
  STRUCT('3abe97bc-ad3c-44a3-8963-5e529d66b6d5', 'ARCHIVED - Application Support'),
  STRUCT('494b1b39-d6d7-46aa-835b-c4598e340d84', 'ICS Operation Excellence'),
  STRUCT('414ee74d-4841-40c0-819a-1b939a6d4e13', 'ARCHIVE - 2024 CSAT'),
  STRUCT('98109733-0b43-49b8-a7ee-d68138291cbe', 'ICAIR Register'),
  STRUCT('942a3438-7e9d-4307-bf4e-42d214c441e0', '2025 GS&O Survey Results'),
  STRUCT('1b39e53b-e2ed-4bae-9bfb-7377c92ce17a', 'Escalation Performance - Pager Duty'),
  STRUCT('6bd60599-0421-4fe9-a2ed-83e135bd2c9b', '[M] GS&O Automation and Analytics - Jira Projects Report'),
  STRUCT('139bca5d-dcbd-47b5-8dbd-a5e6341743dc', '[M] Wanda Transcript'),
  STRUCT('b951b0fa-3e9d-4c03-a6c6-619bff9ee5d5', 'Wanda_UAT'),
  STRUCT('8f3c556b-1b42-42aa-8929-da59312e3111', 'Wanda Performance (Internal)'),
  STRUCT('6d5537bd-e5c3-4d43-9394-6fffa70767dc', 'Ad-hoc Reporting'),
  STRUCT('385bd353-b37e-4023-bc7a-ea172dbb810d', 'Wanda UAT Performance Multi Agent'),
  STRUCT('1a0c0c45-c262-442e-881a-4c803dd6c6e2', 'Wanda Troubleshooting'),
  STRUCT('1d1f3e19-6202-48d1-b54a-9a968c91884c', 'Summary of customer / circuit / sum of total capacity impact analysis'),
  STRUCT('370380bb-99e6-4038-ba14-39f6733d61c3', 'GSD Test'),
  STRUCT('7df80855-0cf7-455c-ad95-e6f57fadd6cf', 'Michael Collins - Assigned Tickets'),
  STRUCT('274b5d11-1fba-4d6f-a0aa-0f6ac09d4d9a', 'Copy of GSO Performance Dashboard'),
  STRUCT('71552d78-b213-429d-ab3d-407115ccb2a2', 'Revenue-CSAT'),
  STRUCT('8e782d0c-e8f1-47e6-b1fd-0a24e314ea9c', 'Sign In App'),
  STRUCT('f0a65af4-51d2-4efc-aa80-5f1ea38b120f', 'test report'),
  STRUCT('1b88ed1d-73a0-4acc-8b47-47565bb7d614', 'Overview Report'),
  STRUCT('4a736011-590b-49c0-84d2-153020ebdb3a', 'Management Report'),
  STRUCT('95af51ff-a406-44b6-b280-17ec258baa0b', 'Customer Survey Dashboard (Expanded)'),
  STRUCT('27075d89-0b1e-46ce-bc27-0707fb6a0b6f', 'Customer Survey Dashboard')
]);

MERGE `pccw-internal-virt-agent-uat.Admin.DataStudioReportLookup` t
USING src s
ON t.looker_studio_report_id = s.looker_studio_report_id
WHEN MATCHED THEN
  UPDATE SET
    t.report_name = CASE WHEN s.report_name IS NOT NULL AND s.report_name != '' THEN s.report_name ELSE t.report_name END,
    t.updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (looker_studio_report_id, report_name, first_seen_at, last_seen_at, updated_at)
  VALUES (s.looker_studio_report_id, s.report_name, NULL, NULL, CURRENT_TIMESTAMP());

SELECT
  (SELECT COUNT(*) FROM src) AS staged_rows,
  (SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.Admin.DataStudioReportLookup`) AS lookup_total_rows,
  (SELECT COUNT(*) FROM `pccw-internal-virt-agent-uat.Admin.DataStudioReportLookup` t JOIN src s USING (looker_studio_report_id) WHERE t.report_name = s.report_name) AS matched_name_rows;
