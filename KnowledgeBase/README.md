# KnowledgeBase

Central runbooks and operational notes for this repo.

## Current Documents

- [Calendar maintenance user OAuth](Calendar_Maintenance_User_OAuth.md) - user-only Calendar consent, secure token storage, verification and deployment.

- `Jira_CloudFunctions_Security.md` - security baseline, deployment guardrails, and verification checks for Jira Cloud Functions.
- `Helix_Service_Spec_v8_Internal.md` - canonical converted Helix Trouble Ticketing API specification.
- `HELIX_ServiceSpec_v8_Detailed_Notes.md` - implementation notes derived from the Helix v8 specification.
- `HELIX_ServiceSpec_v8_Field_Matrix.md` - field and operation matrix for Helix ticket automation.
- `Jira_to_Helix_Automation_Admin_Instructions.md` - production Jira automation setup for the Jira-to-Helix function.
- `Jira_to_Helix_Duplication_Automation_Blueprint.md` - Jira-to-Helix duplication design and workflow blueprint.
- `LinxaAPI.md` - Linxa Connect API endpoint and data schema reference (OAS 3.1).
- `Linxa_CDR_Datapipe_Architecture.md` - planning notes for a future Linxa CDR API-to-BigQuery sync through the existing VPC connector pattern.
- `Linxa_API_Integration_Guide.md` - detailed Linxa API connection, authentication, CDR, pagination, VPC, and security guidance.
- `RemedyJira.md` - schema and semantics reference for `pccw-internal-virtual-agent.wanda_ds.RemedyJira`.
- `RemedyJiraWorkLogView.md` - LLM-oriented schema and semantics reference for `pccw-internal-virtual-agent.wanda_ds.RemedyJiraWorkLogView`.
- `VPC_UAT.md` - UAT VPC connector and Cloud Functions deployment guidance.

## Usage

Before changing infra, deployment scripts, IAM, schedulers, or runtime identities, check the relevant runbook here first.