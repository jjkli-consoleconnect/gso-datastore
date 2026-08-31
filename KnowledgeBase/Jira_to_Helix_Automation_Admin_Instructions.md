# Jira Automation Rule Setup - Production MSS (Admin Instructions)

## Purpose

Create a Jira Automation rule in **production Jira** (`https://consoleconnect.atlassian.net`) that triggers the `mss-to-remedy-create-prod` Cloud Function when an MSS ticket is closed. The function duplicates the closed ticket into Helix, replays comments as worklogs, and closes the Helix ticket.

## Prerequisites

- Admin access to **production** Jira (`https://consoleconnect.atlassian.net`)
- The Cloud Function is already deployed and reachable at:
  `https://mss-to-remedy-create-prod-c6zqodieea-nw.a.run.app`

## Step-by-step

### 1. Navigate to Automations

1. Go to `https://consoleconnect.atlassian.net`
2. Click **Settings** (gear icon, top right)
3. Click **Automations** (under Products)

### 2. Create a new rule

1. Click **Create rule**
2. Choose **Issue transitioned** as the trigger

### 3. Configure the trigger

- **Trigger**: Issue transitioned
- **From status**: (leave empty - any)
- **To status**: Select ALL of:
  - `Resolved Customer Tracking`
  - `Resolved`
  - `Parked`
  - `Cancelled`
- **Project**: Select the **MSS** project (production)

### 4. Add the condition

1. Click **Add condition**
2. Choose **Issue fields condition**
3. Configure:
   - Field: `Remedy Ticket Number (migrated)`
   - Condition: `is empty`
4. This ensures the rule only fires when no Remedy/Helix ticket number exists yet, preventing duplicate Helix tickets.

### 5. Add the webhook action

1. Click **Add action**
2. Choose **Send web request**
3. Configure:
   - **Method**: `POST`
   - **Webhook URL**: `https://mss-to-remedy-create-prod-c6zqodieea-nw.a.run.app`
   - **Headers**: Add one header:
     - Name: `Content-Type`
     - Value: `application/json`
   - **Webhook body**: Select **Issue** (this is critical - the body must include the issue data)
   - **Send issue**: `true` (IMPORTANT - must be enabled, see note below)
   - **Custom body**: leave empty

### 6. Name and enable the rule

1. Click **Rename rule** and give it a clear name, e.g.:
   `Jira Closed -> Helix PROD Webhook`
2. Click **Turn on rule**

## Critical notes for the admin

### `Send issue` MUST be enabled

The Cloud Function requires the issue data in the webhook body to determine the Jira key and closed status. If `Send issue` is disabled, the function receives an empty body and returns `400 Invalid JSON payload`. The rule will appear to "run" but nothing will be synced.

### Use production Jira, not the sandbox

This rule must be created in **production** (`consoleconnect.atlassian.net`), NOT the sandbox (`consoleconnect-sandbox-824.atlassian.net`). The Cloud Function is hardcoded to talk to production Jira and production Helix. Creating the rule in the sandbox would cause the function to create production Helix tickets from sandbox Jira issues.

### Project filter

Select the **production MSS project**. The sandbox MSS project has a different project ID and must not be used.

## Verification

After the rule is enabled:

1. Close an MSS ticket in production (transition to one of the four statuses above)
2. Check the Cloud Function logs:
   `https://console.cloud.google.com/logs/query?project=pccw-internal-virtual-agent&resource=cloud_function&filter=resource.labels.function_name="mss-to-remedy-create-prod"`
3. Confirm a log entry appears with `Processing closed-ticket duplication for MSS-XXXX`
4. Confirm the response shows `"status": "success"` and a `helix_id`
5. Check the Jira ticket - the `Remedy Ticket Number (migrated)` field should now contain the Helix ID

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No log entry in Cloud Function | Rule not firing, or wrong project/status filter | Verify rule is enabled and project/status filters match |
| `400 Invalid JSON payload` in logs | `Send issue` is disabled | Enable `Send issue` in the webhook action |
| `200 ignored` in logs | Body sent but no issue data, or event not recognized | Verify `Send issue` is enabled and body includes issue |
| `404` when fetching Jira issue | Rule in sandbox, not production | Recreate rule in production Jira |
| No Helix ticket created | Condition not met (Remedy field not empty) | Verify the Remedy Ticket Number field is empty on the test ticket |