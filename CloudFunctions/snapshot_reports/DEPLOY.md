# Deployment Guide: Snapshot Reports Cloud Function

## Prerequisites
Ensure you have `gcloud` CLI installed and authenticated.

## Step 1: Authenticate with GCP
```powershell
gcloud auth login
gcloud config set project pccw-internal-virt-agent-uat
```

## Step 2: Create Pub/Sub Topic (if not exists)
```powershell
gcloud pubsub topics create gmail-snapshot-reports --project=pccw-internal-virt-agent-uat
```

## Step 3: Deploy snapshot_reports Cloud Function
```powershell
cd "G:\My Drive\Scripts\CloudFunctions\snapshot_reports"

gcloud functions deploy snapshot_reports `
  --gen2 `
  --runtime=python311 `
  --region=us-central1 `
  --source=. `
  --entry-point=process_snapshot_report `
  --trigger-topic=gmail-snapshot-reports `
  --timeout=540s `
  --memory=512MB `
  --service-account=gmail-bq-processor@pccw-internal-virt-agent-uat.iam.gserviceaccount.com `
  --project=pccw-internal-virt-agent-uat
```

## Step 4: Redeploy gmail_checker to include new pattern
```powershell
cd "G:\My Drive\Scripts\CloudFunctions\gmail_checker"

gcloud functions deploy gmail_checker `
  --gen2 `
  --runtime=python311 `
  --region=us-central1 `
  --source=. `
  --entry-point=check_gmail `
  --trigger-topic=gmail-checker-trigger `
  --timeout=540s `
  --memory=256MB `
  --service-account=gmail-bq-processor@pccw-internal-virt-agent-uat.iam.gserviceaccount.com `
  --project=pccw-internal-virt-agent-uat
```

## Step 5: Test the Pipeline

### Manually trigger gmail_checker to scan for snapshot emails:
```powershell
gcloud pubsub topics publish gmail-checker-trigger --message='{"trigger":"manual"}' --project=pccw-internal-virt-agent-uat
```

### Monitor logs:
```powershell
# Check gmail_checker logs
gcloud functions logs read gmail_checker --region=us-central1 --limit=50 --project=pccw-internal-virt-agent-uat

# Check snapshot_reports logs
gcloud functions logs read snapshot_reports --region=us-central1 --limit=50 --project=pccw-internal-virt-agent-uat
```

## Verification Checklist
- [ ] Topic `gmail-snapshot-reports` created
- [ ] Function `snapshot_reports` deployed successfully
- [ ] Function `gmail_checker` redeployed with new pattern
- [ ] Test email processed successfully
- [ ] Data appears in `Snapshot.RemedyEscalationSnapshot` and `Snapshot.RemedyOutstandingSnapshot`
- [ ] Gmail messages marked as read and label removed
- [ ] Pipeline run logged in `Snapshot.PipelineRuns`

## Troubleshooting
If deployment fails with service account error, verify that the service account has:
- Gmail API access via OAuth token in Secret Manager
- BigQuery Data Editor role
- Pub/Sub Publisher role
