#!/bin/bash
set -e

PROJECT_ID="pccw-internal-virtual-agent"
REGION="europe-west2"
FUNCTION_NAME="jira-tickets-sync"
MEMORY="1024MB"
TIMEOUT="540s"
RUNTIME="python311"
VPC_CONNECTOR="eu-prod-wanda-vpc-conn"
SERVICE_ACCOUNT="jira-sync-runtime@pccw-internal-virtual-agent.iam.gserviceaccount.com"

echo "Deploying Jira Tickets Cloud Function..."
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
  --no-allow-unauthenticated \
  --memory=$MEMORY \
  --timeout=$TIMEOUT \
  --vpc-connector="projects/$PROJECT_ID/locations/$REGION/connectors/$VPC_CONNECTOR" \
  --egress-settings=all \
  --service-account=$SERVICE_ACCOUNT \
  --project=$PROJECT_ID

echo ""
echo "✓ Jira Tickets Cloud Function deployed successfully!"
