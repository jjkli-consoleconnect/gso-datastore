#!/bin/bash
# Deploy PagerDuty sync function to Google Cloud

PROJECT_ID="pccw-internal-virt-agent-uat"
REGION="europe-west2"
FUNCTION_NAME="pagerduty-sync"
RUNTIME="python312"
MEMORY="2048MB"
TIMEOUT="540s"
SERVICE_ACCOUNT="cloud-functions-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Deploying $FUNCTION_NAME to Google Cloud..."

gcloud functions deploy $FUNCTION_NAME \
  --runtime $RUNTIME \
  --region $REGION \
  --project $PROJECT_ID \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point pagerduty_sync \
  --memory $MEMORY \
  --timeout $TIMEOUT \
  --service-account $SERVICE_ACCOUNT \
  --set-env-vars "LOG_LEVEL=INFO" \
  --source .

if [ $? -eq 0 ]; then
  echo "✓ Function deployed successfully"
  gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --project $PROJECT_ID
else
  echo "✗ Deployment failed"
  exit 1
fi
