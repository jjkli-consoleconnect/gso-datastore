# MSS-to-Helix Create (UAT) Deployment Guide

## Prerequisites
- Secrets configured in Secret Manager (already done):
  - `jira-to-helix-jira-user-email`
  - `jira-to-helix-jira-api-token`
  - `jira-to-helix-uat-helix-auth0-client-id`
  - `jira-to-helix-uat-helix-auth0-client-secret`
  - `jira-to-helix-uat-host-name`

- BigQuery table created: `Testing.jira_to_helix_sync` ✓
- BigQuery table (comment idempotency): `Testing.jira_to_helix_comment_sync` (auto-created by function on first comment event)

- VPC Connector ready: `eu-uat-wanda-vpc-conn` (READY, EU)

## Deploy CloudFunction

```bash
# From workspace root
gcloud functions deploy mss-to-remedy-create-uat \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point jira_to_helix_create_uat \
  --project pccw-internal-virt-agent-uat \
  --region europe-west2 \
  --vpc-connector eu-uat-wanda-vpc-conn \
  --set-env-vars DRY_RUN=false \
  --source CloudFunctions/jira-to-helix/mss-to-remedy-create-uat/ \
  --timeout 120 \
  --memory 512MB
```

After deploy, GCP outputs:
```
Trigger URL: https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/mss-to-remedy-create-uat
```

## MSS Automation Setup (Sandbox)

1. Go: https://consoleconnect-sandbox-824.atlassian.net
2. Settings → Automations (left sidebar)
3. Create new rule:
  - **Trigger**: Issue Created
   - **Filter**: `project = MSS`
   - **Action**: Send web request
    - **URL**: `https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/mss-to-remedy-create-uat`
     - **HTTP Method**: POST
     - **Headers**: `Content-Type: application/json`
     - **Body**: Leave as "Empty" (Jira auto-includes full webhook payload)
  - **Save**

4. Create second rule for worklog sync:
  - **Trigger**: Issue Commented
  - **Filter**: `project = MSS`
  - **Action**: Send web request
    - **URL**: `https://europe-west2-pccw-internal-virt-agent-uat.cloudfunctions.net/mss-to-remedy-create-uat`
    - **HTTP Method**: POST
    - **Headers**: `Content-Type: application/json`
    - **Body**: Leave as default Jira payload (must include `issue` and `comment`)
  - **Save**

## Test Flow

1. Create MSS issue in sandbox Jira: "Test Incident"
2. CloudFunction logs appear in Cloud Logging
3. BigQuery table records sync attempt
4. Helix sandbox should have new troubleTicket with externalId = MSS-XXX
5. Jira issue customfield_10647 updated with Helix ID
6. Email alert sent to `jjkli-consoleconnect-aaaat6e6tqjcdqmox62y2vcqfi@consoleconnect.org.slack.com`

For comment sync test:
1. Add comment to same MSS issue
2. CloudFunction logs should show comment sync path
3. Helix ticket should show a new worklog with type `JIRA Work Log`
4. BigQuery `Testing.jira_to_helix_comment_sync` should record the comment ID with `success`

## Dry-Run Mode

To test without creating Helix tickets:
```bash
gcloud functions deploy mss-to-remedy-create-uat \
  --update-env-vars DRY_RUN=true \
  ...
```

Then toggle back to `DRY_RUN=false` when ready for live.

## Monitoring

- Logs: `https://console.cloud.google.com/logs/query?project=pccw-internal-virt-agent-uat&resource=cloud_function&filter=resource.labels.function_name="mss-to-remedy-create-uat"`
- BigQuery ticket sync: `SELECT * FROM pccw-internal-virt-agent-uat.Testing.jira_to_helix_sync ORDER BY created_timestamp DESC`
- BigQuery comment sync: `SELECT * FROM pccw-internal-virt-agent-uat.Testing.jira_to_helix_comment_sync ORDER BY created_timestamp DESC`

## Troubleshooting

**Jira webhook not reaching CF?**
- Verify Jira Automation rule created ✓
- Check CF has `allow-unauthenticated` ✓
- Verify VPC connector state: READY ✓

**Helix creation failing?**
- Check Helix token generation (auth endpoint reachable)
- Verify payload schema matches Helix expectations
- Check BigQuery table for error_message field

**Jira backlink not updating?**
- Verify Jira API credentials valid
- Check customfield_10647 exists in Jira
- Ensure Jira user has permission to edit field

## Next Steps

After deployment:
1. Test in UAT (dry-run mode first)
2. Verify BigQuery idempotency working (same issue → cached response)
3. Verify Jira backlink + Helix creation
4. Configure email alerts (SendGrid or SMTP)
5. Go live
