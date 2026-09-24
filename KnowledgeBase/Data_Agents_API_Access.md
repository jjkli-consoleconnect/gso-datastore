# Google Cloud Data Agents API Access

This runbook documents access to the Gemini Data Analytics Data Agents API for the UAT BigQuery agent.

## Verified target

| Field | Value |
|---|---|
| GCP project | `pccw-internal-virt-agent-uat` |
| Location | `eu` |
| Data Agent | `gso-center-operations-data-analyst-eu` |
| Resource name | `projects/pccw-internal-virt-agent-uat/locations/eu/dataAgents/gso-center-operations-data-analyst-eu` |
| API service | `geminidataanalytics.googleapis.com` |
| EU endpoint | `geminidataanalytics.eu.rep.googleapis.com` |

## Important: use the regional endpoint

Requests to the global endpoint returned `403 Forbidden` for this EU-hosted Data Agent. Use:

```text
https://geminidataanalytics.eu.rep.googleapis.com
```

The resource name still uses location `eu`.

## Authentication and quota project

```powershell
$token = (gcloud auth print-access-token --account='jjkli@consoleconnect.com').Trim()
```

Send both headers:

```text
Authorization: Bearer <access-token>
X-Goog-User-Project: pccw-internal-virt-agent-uat
```

Required permissions include:

```text
geminidataanalytics.dataAgents.get
geminidataanalytics.dataAgents.list
geminidataanalytics.dataAgents.update
```

The console showed the account with the inherited **Gemini Data Analytics Data Agent Owner** role.

## Read a Data Agent

The `get` method returns the full definition, including:

```text
dataAnalyticsAgent.stagingContext.glossaryTerms
```

```powershell
$token = (gcloud auth print-access-token --account='jjkli@consoleconnect.com').Trim()
$url = 'https://geminidataanalytics.eu.rep.googleapis.com/v1beta/projects/pccw-internal-virt-agent-uat/locations/eu/dataAgents/gso-center-operations-data-analyst-eu'
$headers = @{
  Authorization = "Bearer $token"
  'X-Goog-User-Project' = 'pccw-internal-virt-agent-uat'
}

$agent = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
$agent.dataAnalyticsAgent.stagingContext.glossaryTerms
```

Expected term shape:

```json
{
  "displayName": "MTTR Target",
  "description": "An incident meets MTTR target when TrueMTTR_mins is 240 or less.",
  "labels": ["mttr", "resolution time", "sla"]
}
```

## List Data Agents

```powershell
$url = 'https://geminidataanalytics.eu.rep.googleapis.com/v1beta/projects/pccw-internal-virt-agent-uat/locations/eu/dataAgents?pageSize=100'
Invoke-RestMethod -Uri $url -Headers $headers -Method Get
```

Use `get_data_agent` to read glossary terms. A list response is for resource discovery and may not include the full `stagingContext`.

## Update glossary terms safely

### Required update mask

The API rejects a PATCH without an update mask:

```text
request.update_mask: update_mask cannot be empty
```

Use the narrow field mask:

```text
dataAnalyticsAgent.stagingContext.glossaryTerms
```

PATCH URL:

```text
https://geminidataanalytics.eu.rep.googleapis.com/v1beta/projects/pccw-internal-virt-agent-uat/locations/eu/dataAgents/gso-center-operations-data-analyst-eu?updateMask=dataAnalyticsAgent.stagingContext.glossaryTerms
```

### PowerShell PATCH pattern

1. GET the current agent.
2. Read the current glossary array.
3. Add or modify terms in memory.
4. Send the complete intended glossary array.
5. GET again and verify the result.

```powershell
$token = (gcloud auth print-access-token --account='jjkli@consoleconnect.com').Trim()
$baseUrl = 'https://geminidataanalytics.eu.rep.googleapis.com/v1beta/projects/pccw-internal-virt-agent-uat/locations/eu/dataAgents/gso-center-operations-data-analyst-eu'
$headers = @{
  Authorization = "Bearer $token"
  'X-Goog-User-Project' = 'pccw-internal-virt-agent-uat'
  'Content-Type' = 'application/json'
}

$current = Invoke-RestMethod -Uri $baseUrl -Headers $headers -Method Get
$terms = @($current.dataAnalyticsAgent.stagingContext.glossaryTerms)
$terms += [pscustomobject]@{
  displayName = 'Example Term'
  description = 'Example glossary description.'
}

$body = @{
  dataAnalyticsAgent = @{
    stagingContext = @{
      glossaryTerms = $terms
    }
  }
} | ConvertTo-Json -Depth 20

$patchUrl = $baseUrl + '?updateMask=dataAnalyticsAgent.stagingContext.glossaryTerms'
Invoke-RestMethod -Uri $patchUrl -Headers $headers -Method Patch -Body $body
```

Do not send only newly created terms unless replacement behavior is intentional. Send the intended complete `glossaryTerms` array.

## Python client

The official client can use the EU regional endpoint:

```python
from google.api_core import client_options
from google.cloud import geminidataanalytics_v1beta as geminidataanalytics

opts = client_options.ClientOptions(
    api_endpoint="geminidataanalytics.eu.rep.googleapis.com"
)
client = geminidataanalytics.DataAgentServiceClient(client_options=opts)

agent_name = (
    "projects/pccw-internal-virt-agent-uat/"
    "locations/eu/dataAgents/gso-center-operations-data-analyst-eu"
)
agent = client.get_data_agent(name=agent_name)
```

The package is `google-cloud-geminidataanalytics`. Interactive local ADC setup:

```powershell
gcloud auth application-default login
```

For CI, use a service account or workload identity rather than a user credential.

## Troubleshooting

### `403 Forbidden`

Check:

1. Use `geminidataanalytics.eu.rep.googleapis.com`.
2. Include `X-Goog-User-Project: pccw-internal-virt-agent-uat`.
3. Confirm the caller has a Data Agent role with `geminidataanalytics.dataAgents.get` and, for PATCH, `geminidataanalytics.dataAgents.update`.
4. Confirm the exact project, location, and agent ID.
5. Check IAM conditions, organization policy, or access restrictions.

Project Owner and Data Agent Owner access can work in the console while an incorrectly routed API request returns `403`.

### `400 INVALID_ARGUMENT`

If the error says `request.update_mask: update_mask cannot be empty`, add:

```text
?updateMask=dataAnalyticsAgent.stagingContext.glossaryTerms
```

### PATCH response shape

The PATCH response may not expose the updated nested glossary in the same shape as a GET response. Always perform a fresh GET after PATCH and verify the glossary count, `displayName`, `description`, and labels.

## Verified UAT glossary update

The following live operation was verified on the EU agent:

- Existing glossary terms before update: `9`
- Jira project terms added: `25`
- Verified glossary terms after update: `34`
- Update mask: `dataAnalyticsAgent.stagingContext.glossaryTerms`

The project mappings were sourced from:

```text
pccw-internal-virt-agent-uat.GSO.JiraTickets
```

The mappings use the Jira project code in `Key` and the project name in `Project`. See the local `KnowledgeBase` and `CloudFunctions/Jira*` sources for datapipe context.

## Safety rules

- GET before PATCH.
- Preserve existing glossary terms unless replacement is intentional.
- Use the EU endpoint for EU Data Agents.
- Include the quota project header.
- Use the narrow glossary update mask.
- GET after PATCH and verify the live result.
- Never put access tokens, refresh tokens, or service-account keys in this repository.

