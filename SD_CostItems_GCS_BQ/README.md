# SD CostItems GCS to BigQuery Processor

This Cloud Run service processes XLSX files from Google Cloud Storage (GCS) bucket `jens-metadata/datapipe/sd_directcosts`, stages the data in a temporary BigQuery table, and merges it into the `SD_CostItems` table in the `pccw-internal-virt-agent-uat.GSO` dataset.

## Features
- Processes XLSX files one by one to handle large files (500k rows, 200MB+).
- Uses a unique UUID for temporary BigQuery tables, deleted after successful merge.
- Merges data based on composite key: `snapshot_date` + `CostItemID`.
- Supports scalable data pipeline with clustering on `snapshot_date`, `StopBillingDate`, `SRStatus`.
- Manual trigger via HTTP GET request to the service URL.
- Automatically moves processed files to `jens-metadata/datapipe/sd_directcosts/archive` to prevent reprocessing.
- Only processes files not already in the archive folder.

## Prerequisites
- Google Cloud Project: `pccw-internal-virt-agent-uat`
- Service Account: `jens-serviceaccount@pccw-internal-virt-agent-uat.iam.gserviceaccount.com`
- Secret: `projects/14417857267/secrets/jens-serviceaccount-key` (contains the service account key JSON)
- BigQuery Dataset: `GSO` exists in the project.
- BigQuery Table: `SD_CostItems` exists with the matching schema (see main.py for schema definition). Create it with clustering on `snapshot_date`, `StopBillingDate`, `SRStatus`.
- GCS Bucket: `jens-metadata` with prefix `datapipe/sd_directcosts/` containing XLSX files.

## Deployment

1. Ensure you have the Google Cloud SDK installed and authenticated:
   ```
   gcloud auth login
   gcloud config set project pccw-internal-virt-agent-uat
   ```

2. Deploy to Cloud Run in the London region (europe-west2):
   ```
   gcloud run deploy sd-costitems-processor \
     --source . \
     --region europe-west2 \
     --allow-unauthenticated \
     --set-secrets GOOGLE_APPLICATION_CREDENTIALS=jens-serviceaccount-key:latest \
     --memory 2Gi \
     --cpu 1 \
     --max-instances 1 \
     --timeout 3600
   ```

   - `--source .`: Builds from the current directory.
   - `--set-secrets`: Mounts the secret as the credentials file.
   - Adjust memory/CPU as needed for large files.
   - `--timeout 3600`: 1 hour timeout for processing.

3. After deployment, note the service URL (e.g., `https://sd-costitems-processor-abc123-ew.a.run.app`).

## Usage

Trigger the processing manually by sending a GET request to the service URL:
```
curl https://sd-costitems-processor-abc123-ew.a.run.app/
```

The service will:
- List all XLSX files in the GCS bucket prefix.
- Process each file: download, parse, stage in temp BigQuery table, merge, clean up.
- Return "Processing complete" on success.

## Schema

The `SD_CostItems` table schema matches the CSV sample, with appropriate BigQuery types (STRING, INT64, FLOAT64, DATE). Date columns are parsed from the XLSX.

## Notes
- Ensure the service account has permissions: BigQuery Data Editor, Storage Object Viewer.
- For production, consider adding logging, error handling, and retries.
- If the table doesn't exist, create it manually or add table creation logic.
- Processing is sequential; for parallel processing, modify the script to use threads or multiple instances.