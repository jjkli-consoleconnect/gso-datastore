$out = 'C:\dev\consoleconnect\Temp\bq-probe\probe.txt'
$proj = 'pccw-internal-virt-agent-uat'
Remove-Item $out -ErrorAction SilentlyContinue
function W($m) { $m | Add-Content -Path $out }
foreach ($loc in 'EU','US','europe-west2','us-central1') {
  $r = "region-$loc"
  W "######## $r ########"
  W '-- VIEWS --'
  W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT table_schema, table_name, use_standard_sql FROM ``$proj``.``$r``.INFORMATION_SCHEMA.VIEWS LIMIT 2" 2>&1 | Out-String)
  W '-- ROUTINES --'
  W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT routine_schema, routine_name, last_altered FROM ``$proj``.``$r``.INFORMATION_SCHEMA.ROUTINES LIMIT 2" 2>&1 | Out-String)
  W '-- TABLES MV --'
  W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT table_schema, table_name, table_type FROM ``$proj``.``$r``.INFORMATION_SCHEMA.TABLES WHERE table_type='MATERIALIZED VIEW' LIMIT 2" 2>&1 | Out-String)
  W '-- VIEW COUNT --'
  W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT COUNT(*) AS view_count FROM ``$proj``.``$r``.INFORMATION_SCHEMA.VIEWS" 2>&1 | Out-String)
}
W '######## EU column probes ########'
W '-- SCHEMATA last_modified_time + location --'
W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT schema_name FROM ``$proj``.``region-EU``.INFORMATION_SCHEMA.SCHEMATA LIMIT 2" 2>&1 | Out-String)
W '-- TABLES last_modified_time --'
W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT table_name, last_modified_time FROM ``$proj``.``region-EU``.INFORMATION_SCHEMA.TABLES LIMIT 1" 2>&1 | Out-String)
W '-- VIEWS ddl probe --'
W (bq query --nouse_legacy_sql --format=csv --project_id=$proj "SELECT table_name FROM ``$proj``.``region-EU``.INFORMATION_SCHEMA.VIEWS LIMIT 1" 2>&1 | Out-String)
W '-- DONE --'
