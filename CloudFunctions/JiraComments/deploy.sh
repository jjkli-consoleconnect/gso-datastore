#!/bin/bash
set -e

PROJECT_ID="pccw-internal-virt-agent-uat"
REGION="europe-west2"
FUNCTION_NAME="jira-comments-sync"
MEMORY="1024MB"
TIMEOUT="540s"
RUNTIME="python311"
VPC_CONNECTOR="eu-uat-wanda-vpc-conn"
SERVICE_ACCOUNT="jira-bigquery@pccw-internal-virt-agent-uat.iam.gserviceaccount.com"

echo "Deploying Jira Comments Cloud Function..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo "VPC Connector: $VPC_CONNECTOR"
echo ""

gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=$RUNTIME \
  --region=$REGION \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --allow-unauthenticated \
  --memory=$MEMORY \
  --timeout=$TIMEOUT \
  --vpc-connector="projects/$PROJECT_ID/locations/$REGION/connectors/$VPC_CONNECTOR" \
  --service-account=$SERVICE_ACCOUNT \
  --project=$PROJECT_ID

echo ""
echo "✓ Jira Comments Cloud Function deployed successfully!"
