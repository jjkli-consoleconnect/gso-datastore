# Wanda 4.0 Workshop - CCAI Jira Backlog Tickets Specification

This document provides an updated, comprehensive specification of all 28 Jira backlog tickets (v2) (5 Parent Tickets and 23 Child Tickets) created following the **Wanda 4.0 Workshop** (16–18 September 2026). It is formatted for direct ingestion by an LLM or automated script to provision tickets via the Jira REST API.

---

## Metadata Summary

* **Version**: v2
* **Field Customization Notes**:  
  * **Components**: Left empty for manual addition in Jira.
  * **Acceptance Criteria**: Embedded directly inside the **Description** field for seamless Jira API creation.
* **Project Key**: CCAI
* **Workshop Dates**: 16–18 September 2026
* **Key Stakeholders**:  
  * **Ken Tam**: Strategic Lead / Sponsor ("The Boss")
  * **Jens Li**: Project Manager / Lead Coordinator
  * **Paulo Gabriel Bertol**: AI Engineer
  * **Jann Rayco**: AI Engineer
  * **Sheldon**: Senior Data Analyst
  * **JC**: Technical Writer

---

## PARENT TICKET 1: Agentic Swarm Architecture &amp; Infrastructure Migration

* **Jira Key**: `CCAI-PARENT-1`
* **Issue Type**: Task (Parent)
* **Summary**: Wanda 4.0 Agentic Swarm Architecture &amp; Infrastructure Migration
* **Assignee**: Paulo Gabriel Bertol / Jann Rayco
* **Reporter**: Jens Li
* **Components**:
* **Priority**: High
* **Description**: Transition Wanda 4.0 from a monolithic sequential orchestrator model to a modular, parallel Agentic Swarm architecture. This includes decomposing the central orchestrator into standalone microservice sub-agents, setting up session tracking in Cloud SQL, implementing identity access management (JumpCloud / Permit.io), and migrating repositories to the Beehive (Console Connect GitHub) environment by end of October.

---

### Child Ticket 1.1: Standalone Sub-Agent Microservices &amp; API Endpoints

* **Jira Key**: `CCAI-CHILD-1.1`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Implement Standalone Sub-Agent Microservices with Individual API Endpoints
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Decouple the legacy single endpoint orchestrator into standalone sub-agent microservices, each exposing individual HTTP endpoints (e.g., `/coordinator`, `/kms`, `/data-analysis`). Enable direct Agent-to-Agent (A2A) protocol communication using standardized payloads.

**Acceptance Criteria:**

  * Standalone endpoints established for Coordinator, KMS, Data Analysis, and Output agents.
  * A2A protocol defined with JSON payloads passed directly between sub-agents.
  * Sub-agent latencies and execution logs independently trackable in GCP Logs Explorer.

---

### Child Ticket 1.2: Concierge &amp; Planner Agent (Butler / Jarvis) Implementation

* **Jira Key**: `CCAI-CHILD-1.2`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Build Concierge Fast-Path &amp; Planner Agent Checklist Architecture
* **Assignee**: Jann Rayco
* **Priority**: High
* **Components**:
* **Description**: Develop a two-tier entry framework:

  1. **Concierge Agent**: Fast-path responder for general/conversational queries (e.g. greetings) without calling LLM reasoning chains.
  2. **Planner Agent (Butler / Jarvis)**: Decomposes complex user queries into a dynamic, step-by-step **Planner Checklist** (identifying required sub-agents and determining sequential vs. parallel execution).

**Acceptance Criteria:**

  * Concierge bypasses heavy agent chains for general intent queries.
  * Planner Agent outputs structured payloads containing `planner_checklist`, `agents_involved`, `execution_mode` (parallel/sequential), and `session_id`.
  * Tested with multi-domain prompts (e.g., requesting ticket summary + KMS troubleshooting steps).

---

### Child Ticket 1.3: Evaluator Gatekeeper &amp; Consolidator Module

* **Jira Key**: `CCAI-CHILD-1.3`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Implement Evaluator Gatekeeper &amp; Output Consolidator
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Build an **Evaluator Gatekeeper** module to re-check sub-agent outputs against the Planner Checklist prior to final delivery. Prevent execution loops and verify data completeness before passing responses to the Consolidator.

**Acceptance Criteria:**

  * Evaluator checks output against checklist criteria and flags incomplete sub-tasks.
  * Prevents recursive sub-agent looping through max-retry evaluation limits.
  * Consolidator merges parallel sub-agent results into a single unified context block.

---

### Child Ticket 1.4: Session &amp; Sub-session Memory Tracking in Cloud SQL

* **Jira Key**: `CCAI-CHILD-1.4`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Implement Main Session ID &amp; Nested Sub-session Memory Tracking in Cloud SQL
* **Assignee**: Jens Li
* **Priority**: Medium
* **Components**:
* **Description**: Design database tables in Cloud SQL to log each conversation's primary `session_id` and nested `sub_session_id` records for each sub-agent execution step. Capture start/end timestamps, agent identifiers, and input/output token counts to pinpoint latency bottlenecks.

**Acceptance Criteria:**

  * Schema deployed to Cloud SQL with `session_id`, `sub_session_id`, `agent_id`, `start_time`, `end_time`, `status`.
  * Latency breakdown per sub-agent visible in BigQuery analytics dashboards.

---

### Child Ticket 1.5: Beehive Code Repository Migration &amp; Security Compliance

* **Jira Key**: `CCAI-CHILD-1.5`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Migrate Web Services &amp; Code Repositories to Beehive (Console Connect GitHub)
* **Assignee**: Jens Li
* **Priority**: High
* **Components**:
* **Description**: Migrate Wanda web services, repositories, and CI/CD pipelines to the corporate **Beehive** environment (Console Connect GitHub repository) by end of October 2026 to comply with corporate security vulnerability scanning standards.

**Acceptance Criteria:**

  * Repositories transferred to Beehive GitHub organization.
  * Automated security vulnerability scanning active in CI/CD pipeline.
  * Deployment access configured for UAT and Production Cloud Run environments.

---

### Child Ticket 1.6: Identity Access Management (IAM), JumpCloud &amp; Permit.io Integration

* **Jira Key**: `CCAI-CHILD-1.6`
* **Parent Key**: `CCAI-PARENT-1`
* **Issue Type**: Sub-task
* **Summary**: Integrate JumpCloud &amp; Permit.io for User Identity &amp; Row-Level Data Permissions
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Centralize user authentication via **JumpCloud** and role-based policy enforcement via **Permit.io**. Transition BigQuery queries from using master service accounts to individual user credentials (Data Viewer role), enabling row-level data restrictions for sensitive datasets (e.g. financial MRC data). Allow agents to act on behalf of authenticated users while logging audit trails.

**Acceptance Criteria:**

  * User identity passed from Slack/Web frontend to sub-agents.
  * Permit.io policy checks enforce row-level access in BigQuery.
  * User ID logged in Remedy/Jira API calls for auditability.

---

## PARENT TICKET 2: Data Strategy, Production Migration &amp; Storage Optimization

* **Jira Key**: `CCAI-PARENT-2`
* **Issue Type**: Task (Parent)
* **Summary**: Wanda 4.0 Data Strategy, Production Migration &amp; Storage Optimization
* **Assignee**: Jens Li / Sheldon
* **Reporter**: Ken Tam
* **Components**:
* **Priority**: High
* **Description**: Execute BigQuery production data migration, align data locations in Europe West 2 (London), optimize database performance by moving Knowledge Management System (KMS) search to Cloud SQL PostgreSQL (`pgvector`), revamp Wanda DB, deprecate CCAI Insight in favor of BigQuery Gemini functions, and enforce strict table schema standards.

---

### Child Ticket 2.1: BigQuery Production Data Migration &amp; Snapshot Replication

* **Jira Key**: `CCAI-CHILD-2.1`
* **Parent Key**: `CCAI-PARENT-2`
* **Issue Type**: Sub-task
* **Summary**: Migrate Live BigQuery Pipelines to Production &amp; Establish UAT Snapshot Replicas
* **Assignee**: Jens Li
* **Priority**: High
* **Components**:
* **Description**: Migrate primary data ingestion pipelines and production datasets from UAT to the Production GCP environment. Configure UAT datasets to act as backup snapshot replicas fed from Production to ensure UAT testing does not impact live performance.

**Acceptance Criteria:**

  * Live data pipelines writing directly to Production BigQuery.
  * Automated snapshot replication from Production to UAT active.
  * Zero data loss verified across historical ticket tables.

---

### Child Ticket 2.2: Regional Dataset Realignment (Europe West 2 / London vs. EU Multi-Region)

* **Jira Key**: `CCAI-CHILD-2.2`
* **Parent Key**: `CCAI-PARENT-2`
* **Issue Type**: Sub-task
* **Summary**: Align BigQuery Datasets to London (Europe West 2) &amp; Retain Vertex AI in EU Multi-Region
* **Assignee**: Jens Li / Sheldon
* **Priority**: Medium
* **Components**:
* **Description**: Align BigQuery datasets to **London (Europe West 2)** alongside Enterprise Data Platform (EDP) to eliminate cross-region join overhead and storage copying costs. Retain Vertex AI in **EU Multi-Region** to avoid token quota exhaustion experienced in London.

**Acceptance Criteria:**

  * BigQuery tables co-located in `europe-west2` (London).
  * Direct SQL joins between Wanda DB and EDP tables working without cross-region errors.
  * Vertex AI API endpoints configured to `EU` multi-region.

---

### Child Ticket 2.3: KMS PostgreSQL Migration (`pgvector` Cloud SQL)

* **Jira Key**: `CCAI-CHILD-2.3`
* **Parent Key**: `CCAI-PARENT-2`
* **Issue Type**: Sub-task
* **Summary**: Migrate KMS Retrieval Tables to Cloud SQL PostgreSQL (`pgvector`)
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Move Knowledge Management System (KMS) vector retrieval tables from BigQuery to existing Cloud SQL PostgreSQL instances using `pgvector`. Achieves sub-5ms lookup latency (down from 1–3s in BigQuery) without incurring additional GCP instance charges.

**Acceptance Criteria:**

  * KMS embeddings ingested into Cloud SQL PostgreSQL using `pgvector`.
  * Retrieval query response times measured at &lt;5ms.
  * Existing Cloud SQL instance utilized without secondary instance billing.

---

### Child Ticket 2.4: Wanda DB Revamp &amp; CCAI Insight Deprecation to BigQuery Gemini Functions

* **Jira Key**: `CCAI-CHILD-2.4`
* **Parent Key**: `CCAI-PARENT-2`
* **Issue Type**: Sub-task
* **Summary**: Deprecate CCAI Insight Daily Jobs &amp; Implement Hourly BigQuery Gemini AI Functions
* **Assignee**: Jens Li
* **Priority**: Medium
* **Components**:
* **Description**: Deprecate legacy CCAI Insight daily batch processing scripts. Implement native BigQuery Gemini SQL functions (`ML.GENERATE_TEXT` / AI functions) scheduled on an hourly basis to perform conversation sentiment analysis, confidence scoring, and intent extraction.

**Acceptance Criteria:**

  * Legacy CCAI Insight daily batch job decommissioned.
  * Hourly BigQuery scheduled queries calling native Gemini functions active.
  * Sentiment scores and confidence levels automatically populated in analytics tables.

---

### Child Ticket 2.5: Data Schema &amp; Field-Naming Standardization Guidelines

* **Jira Key**: `CCAI-CHILD-2.5`
* **Parent Key**: `CCAI-PARENT-2`
* **Issue Type**: Sub-task
* **Summary**: Establish Data Schema &amp; Descriptive Field-Naming Standards for Incoming Ingests
* **Assignee**: Sheldon / Jens Li
* **Priority**: Medium
* **Components**:
* **Description**: Define and enforce naming conventions, descriptive field names, and manual column descriptions in BigQuery schema definitions. Ensures LLM SQL generation agents accurately identify and join columns across incoming datasets (e.g. shift handovers, cable events).

**Acceptance Criteria:**

  * Published schema guidelines for field naming and description metadata.
  * Column-level descriptions populated for all ticket, worklog, and shift handover tables.
  * Verified BigQuery Agent SQL generation accuracy improves on test queries.

---

## PARENT TICKET 3: BMC Helix Remedy Integration &amp; Incident Automation MVPs

* **Jira Key**: `CCAI-PARENT-3`
* **Issue Type**: Task (Parent)
* **Summary**: BMC Helix Remedy Integration &amp; Incident Automation MVPs
* **Assignee**: Paulo Gabriel Bertol / Jann Rayco
* **Reporter**: Ken Tam
* **Components**:
* **Priority**: High
* **Description**: Build modular, non-intrusive integrations with BMC Helix Remedy operating parallel to Remedy. Execute three core MVPs: automated troubleshooting for No Fault Found (NFF) cases to reduce MTTR, background context enrichment in BMC Smart IT UI via Innovation Studio, and auto-generated Reason for Outage (RFO) closure notifications.

---

### Child Ticket 3.1: MVP 1 — Automated No Fault Found (NFF) Ticket Troubleshooting &amp; Resolution

* **Jira Key**: `CCAI-CHILD-3.1`
* **Parent Key**: `CCAI-PARENT-3`
* **Issue Type**: Sub-task
* **Summary**: Build Automated NFF Diagnostic Scripts &amp; Auto-Resolution Workflow
* **Assignee**: Jann Rayco
* **Priority**: High
* **Components**:
* **Description**: Automate diagnostics upon ticket creation for customer-reported No Fault Found (NFF) cases (\~5,500 tickets over 6 months, 92% customer-reported, baseline MTTR \~17 hours). Trigger automated loopback/ping scripts upon creation; if connectivity criteria pass, post test results to worklogs and change status to Resolved (target MTTR: 3 minutes).

**Acceptance Criteria:**

  * Immediate webhook trigger upon BMC Remedy ticket creation.
  * Automated diagnostic script executes IP connectivity, traceroute, and interface checks within 3 minutes.
  * Validated pass cases auto-populate worklog evidence and set status to Resolved.

---

### Child Ticket 3.2: MVP 2 — Smart IT UI Context Enrichment &amp; Innovation Studio Widgets

* **Jira Key**: `CCAI-CHILD-3.2`
* **Parent Key**: `CCAI-PARENT-3`
* **Issue Type**: Sub-task
* **Summary**: Inject Innovation Studio API Widgets for Smart IT Context Enrichment
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Configure Innovation Studio background API widgets in BMC Helix Smart IT. Upon opening a ticket, automatically pull and display similar historical tickets, circuit/SR history, and KMS troubleshooting steps directly in the Smart IT agent sidebar.

**Acceptance Criteria:**

  * Smart IT UI sidebar widget loaded via Innovation Studio.
  * Background API fetches similar historical cases and KMS troubleshooting guides based on `circuit_id` / `service_request_id`.
  * Zero manual prompting required by human agents to view context.

---

### Child Ticket 3.3: MVP 3 — Automated RFO Summaries &amp; Customer Closure Notifications

* **Jira Key**: `CCAI-CHILD-3.3`
* **Parent Key**: `CCAI-PARENT-3`
* **Issue Type**: Sub-task
* **Summary**: Build Automated Reason for Outage (RFO) Generator for Ticket Closure
* **Assignee**: Jann Rayco
* **Priority**: Medium
* **Components**:
* **Description**: Synthesize ticket worklog history upon root cause identification to automatically draft a concise Reason for Outage (RFO) summary. Attach the generated RFO to customer closure notification emails.

**Acceptance Criteria:**

  * RFO generated automatically when ticket status transitions to Pending Closure.
  * Formatted text appended to Remedy customer notification template.
  * Verified for clarity and technical accuracy against worklog evidence.

---

## PARENT TICKET 4: Tool Registry, Testing Frameworks &amp; Output Standardization

* **Jira Key**: `CCAI-PARENT-4`
* **Issue Type**: Task (Parent)
* **Summary**: Wanda 4.0 Tool Registry, Output Standardization &amp; Testing Frameworks
* **Assignee**: Jann Rayco / Paulo Gabriel Bertol
* **Reporter**: Jens Li
* **Components**:
* **Priority**: High
* **Description**: Establish standardized tool templates and a central Tool Registry for agent discovery. Build reusable tools including an IAM authentication tool. Implement GitHub CI/CD unit testing and LLM self-auditing fields. Decouple report generation into a dedicated Output Agent, and optimize BigQuery agent Cloud Run prompt wrappers to reduce latency.

---

### Child Ticket 4.1: Centralized Tool Registry &amp; Standardized Tool Templates

* **Jira Key**: `CCAI-CHILD-4.1`
* **Parent Key**: `CCAI-PARENT-4`
* **Issue Type**: Sub-task
* **Summary**: Define Standardized Tool Templates &amp; Central Tool Registry Catalog
* **Assignee**: Jann Rayco
* **Priority**: High
* **Components**:
* **Description**: Define standardized tool templates (intuitive naming conventions, functional descriptions, dynamic JSON input/output schemas, parameter type constraints). Register all microservice tools in a central Tool Registry for dynamic discovery by sub-agents.

**Acceptance Criteria:**

  * Standardized JSON tool schema definition published.
  * Tool Registry service operational with registration/lookup endpoints.
  * Sub-agents dynamically query registry to invoke tools.

---

### Child Ticket 4.2: Reusable Identity Access Management (IAM) Sub-Agent Tool

* **Jira Key**: `CCAI-CHILD-4.2`
* **Parent Key**: `CCAI-PARENT-4`
* **Issue Type**: Sub-task
* **Summary**: Build Centralized Reusable IAM Tool for Sub-Agents &amp; External Interfaces
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Encapsulate identity authentication and role verification logic into a standalone, reusable IAM tool. Enable sub-agents, GLA, Confluence, and external services to verify user permissions through a single tool interface.

**Acceptance Criteria:**

  * Central IAM tool registered in Tool Registry.
  * Sub-agents successfully pass user token to IAM tool and receive permission scopes.
  * Invalid permissions throw standardized access denied status codes.

---

### Child Ticket 4.3: GitHub CI/CD Unit Testing &amp; LLM Self-Auditing Framework

* **Jira Key**: `CCAI-CHILD-4.3`
* **Parent Key**: `CCAI-PARENT-4`
* **Issue Type**: Sub-task
* **Summary**: Implement CI/CD Unit Testing &amp; LLM Audit Field Self-Verification
* **Assignee**: Jann Rayco / Paulo Gabriel Bertol
* **Priority**: High
* **Components**:
* **Description**: Implement dual-layer testing:

  1. Standard unit testing in GitHub CI/CD pipelines for deterministic code and tools.
  2. LLM self-auditing via mandatory `audit_field` output JSON attributes, allowing verifier LLMs to review thought processes and flag non-deterministic errors prior to release deployment.

**Acceptance Criteria:**

  * GitHub Actions CI/CD pipeline runs automated unit tests on every pull request.
  * LLM outputs include structured `audit_field` explaining reasoning logic.
  * Automated auditing suite parses `audit_field` logs to detect reasoning anomalies.

---

### Child Ticket 4.4: Dedicated Output Agent &amp; Modular Report Exporters

* **Jira Key**: `CCAI-CHILD-4.4`
* **Parent Key**: `CCAI-PARENT-4`
* **Issue Type**: Sub-task
* **Summary**: Build Dedicated Output Agent for Standardized Report Templates (RCA, RFO, Handover)
* **Assignee**: Jann Rayco
* **Priority**: Medium
* **Components**:
* **Description**: Decouple document formatting logic from individual sub-agents into a dedicated Output Agent. Implement predefined layout templates for Root Cause Analysis (RCA), Reason for Outage (RFO), Incident Reports, and Shift Handover reports. Support unstructured exports (PDF, Google Docs, CSV) featuring standard company headers and logos.

**Acceptance Criteria:**

  * Output Agent microservice deployed with template engines for RCA, RFO, Incident Report, and Shift Handover.
  * Unstructured responses formatted into Google Docs and PDF with corporate header/logo.
  * Individual sub-agents hand off raw JSON data to Output Agent for final styling.

---

### Child Ticket 4.5: BigQuery Wrapper Prompt Optimization (`ticket_analysis_agent.py`)

* **Jira Key**: `CCAI-CHILD-4.5`
* **Parent Key**: `CCAI-PARENT-4`
* **Issue Type**: Sub-task
* **Summary**: Optimize Cloud Run Prompt Wrapper in `ticket_analysis_agent.py`
* **Assignee**: Paulo Gabriel Bertol / Jens Li
* **Priority**: High
* **Components**:
* **Description**: Strip redundant and conflicting instruction blocks from `ticket_analysis_agent.py` in Cloud Run. Rely directly on native BigQuery agent schema instructions to eliminate prompt bloat and calculation errors (e.g. MTTR discrepancies).

**Acceptance Criteria:**

  * Redundant instructions removed from `ticket_analysis_agent.py`.
  * Query response times reduced by 30% (from \~80s down to \~55s).
  * Calculated MTTR metrics verified for accuracy against native BigQuery queries.

---

## PARENT TICKET 5: Operations Command Center, GCP Observability &amp; Support Guardrails

* **Jira Key**: `CCAI-PARENT-5`
* **Issue Type**: Task (Parent)
* **Summary**: Command Center Monitoring, GCP Observability &amp; Support Guardrails
* **Assignee**: Jens Li / Sheldon / Paulo Gabriel Bertol
* **Reporter**: Ken Tam
* **Components**:
* **Priority**: Medium
* **Description**: Establish GCP Observability and Command Center monitoring covering Cloud Run services, GCP billing/token usage, and 10 core data sync pipelines. Standardize GCP status error codes, set up Slack/PagerDuty alert escalations, and enable IT Helpdesk agents with Wanda documentation and contractor GTA access workflows.

---

### Child Ticket 5.1: GCP Observability, Billing Anomaly Alerts &amp; Resource Monitoring

* **Jira Key**: `CCAI-CHILD-5.1`
* **Parent Key**: `CCAI-PARENT-5`
* **Issue Type**: Sub-task
* **Summary**: Configure GCP Observability Dashboards, Token Tracking &amp; Billing Alerts
* **Assignee**: Jens Li / Paulo Gabriel Bertol
* **Priority**: Medium
* **Components**:
* **Description**: Set up GCP Observability dashboards to monitor Cloud Run availability, backend service latencies, LLM input/output token consumption, and GCP billing anomalies (alerting at 50% budget threshold).

**Acceptance Criteria:**

  * GCP Observability dashboard created showing Cloud Run health and latency metrics.
  * Billing budget alert configured at 50% threshold notifying lead stakeholders via email.
  * Daily token usage logged and displayed by model/sub-agent.

---

### Child Ticket 5.2: Data Pipeline Synchronization Monitoring (10 Core Data Pipes)

* **Jira Key**: `CCAI-CHILD-5.2`
* **Parent Key**: `CCAI-PARENT-5`
* **Issue Type**: Sub-task
* **Summary**: Implement Synchronization Health Monitoring Across 10 Ingestion Pipelines
* **Assignee**: Jens Li
* **Priority**: High
* **Components**:
* **Description**: Establish automated real-time and daily health checks across \~10 core data pipelines mirroring Remedy, Jira, PagerDuty, EDP, and subsea cable event Google Sheets into BigQuery.

**Acceptance Criteria:**

  * Automated check verifies file/table ingestion success every 3 minutes.
  * Real-time Slack notifications dispatched immediately upon pipe ingestion failure.
  * Automated daily summary email generated highlighting recurring error patterns.

---

### Child Ticket 5.3: Standardized GCP Error Status Codes &amp; Retrospective Logging

* **Jira Key**: `CCAI-CHILD-5.3`
* **Parent Key**: `CCAI-PARENT-5`
* **Issue Type**: Sub-task
* **Summary**: Standardize Error Handling, Status Codes &amp; BigQuery Retrospective Logging
* **Assignee**: Paulo Gabriel Bertol
* **Priority**: Medium
* **Components**:
* **Description**: Standardize application error status codes (e.g., status code 8 / HTTP 429 for resource exhaustion, status code 5 / HTTP 404 for missing resources). Log error codes to BigQuery for retrospective reviews and route non-critical errors to Slack and critical failures to PagerDuty.

**Acceptance Criteria:**

  * Error handling wrapper maps internal exceptions to standardized GCP status codes.
  * Error logs captured in BigQuery for weekly team retrospective analysis.
  * Critical web service outages trigger PagerDuty phone/SMS escalation alerts.

---

### Child Ticket 5.4: IT Helpdesk Enablement &amp; Contractor Access Workflow (GTA Tickets)

* **Jira Key**: `CCAI-CHILD-5.4`
* **Parent Key**: `CCAI-PARENT-5`
* **Issue Type**: Sub-task
* **Summary**: Ingest Wanda Support Knowledge Base &amp; Configure Contractor GTA Access Workflow
* **Assignee**: Sheldon / Jens Li
* **Priority**: Medium
* **Components**:
* **Description**: Ingest Wanda technical support documentation into the Wanda knowledge base so IT Helpdesk agents can self-serve user support queries. Establish a standardized GTA ticket workflow for managing contractor access overrides.

**Acceptance Criteria:**

  * Support documentation ingested into KMS PostgreSQL database.
  * IT Helpdesk agents successfully query Wanda for platform troubleshooting steps.
  * GTA ticket process defined and documented for contractor access overrides.