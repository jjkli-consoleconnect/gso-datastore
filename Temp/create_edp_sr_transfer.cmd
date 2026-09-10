@echo off
rem Create cross_region_copy transfer GSOEDPLink (europe-west2) -> Mirror (EU)
for /f "usebackq delims=" %%i in (`gcloud auth print-access-token`) do set TOKEN=%%i

curl -s -X POST "https://bigquerydatatransfer.googleapis.com/v1/projects/14417857267/locations/eu/transferConfigs" ^
  -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
  -d "{\"displayName\":\"EDP-SR EU Copy\",\"destinationDatasetId\":\"Mirror\",\"dataSourceId\":\"cross_region_copy\",\"schedule\":\"every day 00:15\",\"params\":{\"source_dataset_id\":\"GSOEDPLink\",\"source_project_id\":\"pccw-internal-virt-agent-uat\",\"overwrite_destination_table\":true}}"



