$views = @(
  @{p='pccw-internal-virt-agent-uat'; d='GSO'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virt-agent-uat\GSO\views\JIRA_HD.sql'},
  @{p='pccw-internal-virt-agent-uat'; d='GSO'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virt-agent-uat\GSO\views\RemedyJira.sql'},
  @{p='pccw-internal-virt-agent-uat'; d='GSO'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virt-agent-uat\GSO\views\GSDT_Cleaned.sql'},
  @{p='pccw-internal-virt-agent-uat'; d='wanda_ds'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virt-agent-uat\wanda_ds\views\RemedyJira.sql'},
  @{p='pccw-internal-virt-agent-uat'; d='wanda_ds'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virtual-agent\wanda_ds\views\SHRPeople.sql'},
  @{p='pccw-internal-virtual-agent'; d='wanda_ds'; f='G:\My Drive\Scripts\BigQuery\pccw-internal-virtual-agent\wanda_ds\views\RemedyJira.sql'}
)
foreach ($v in $views) {
  $name = [IO.Path]::GetFileNameWithoutExtension($v.f)
  $sql = (Get-Content $v.f -Raw)
  $ddl = "CREATE OR REPLACE VIEW $($v.p).$($v.d).$name AS`n$sql"
  "DEPLOYING $($v.p).$($v.d).$name"
  $ddl | bq query --use_legacy_sql=$false --format=quiet
  if ($LASTEXITCODE -ne 0) { "FAILED $name" } else { "OK $name" }
}
'ALL DONE'