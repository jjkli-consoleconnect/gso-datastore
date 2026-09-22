#!/bin/bash
# Deploys the pipeline_daily_report Cloud Function (gen2, HTTP) + Cloud Scheduler job.
# Requires: gcloud auth with roles/functions.admin, roles/iam.serviceAccountUser,
#           roles/scheduler.admin in the project.
set -e

PROJECT_ID="pccw-internal-virt-agent-uat"
REGION="europe-west2"
FUNCTION_NAME="pipeline-daily-report"
RUNTIME="python311"
MEMORY="256MB"
TIMEOUT="120s"
ENTRYPOINT="main"

# Service account the function runs as, and Scheduler uses to invoke it.
# The default compute SA already has bigquery + secretmanager access (used by the
# other data-pipe CFs), so no new SA/role grants are needed.
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-14417857267-compute@developer.gserviceaccount.com}"
SCHEDULE="0 9 * * *"
SCHEDULE_TZ="Asia/Hong_Kong"

echo "Deploying ${FUNCTION_NAME} in ${PROJECT_ID}/${REGION} ..."

gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --runtime="${RUNTIME}" \
  --region="${REGION}" \
  --source=. \
  --entry-point="${ENTRYPOINT}" \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --project="${PROJECT_ID}"

URL="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}"

if gcloud scheduler jobs describe "pipeline-daily-report-schedule" \
     --project="${PROJECT_ID}" --location="${REGION}" >/dev/null 2>&1; then
  echo "Updating existing scheduler job..."
  gcloud scheduler jobs update http "pipeline-daily-report-schedule" \
    --schedule="${SCHEDULE}" --time-zone="${SCHEDULE_TZ}" --uri="${URL}" \
    --http-method=GET \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" --oidc-token-audience="${URL}" \
    --project="${PROJECT_ID}" --location="${REGION}"
else
  echo "Creating scheduler job..."
  gcloud scheduler jobs create http "pipeline-daily-report-schedule" \
    --schedule="${SCHEDULE}" --time-zone="${SCHEDULE_TZ}" --uri="${URL}" \
    --http-method=GET \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" --oidc-token-audience="${URL}" \
    --project="${PROJECT_ID}" --location="${REGION}"
fi

echo ""
echo "OK: deployed ${FUNCTION_NAME} + daily job (${SCHEDULE} ${SCHEDULE_TZ})."