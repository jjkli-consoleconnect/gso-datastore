# Wanda — In-House ADK Chatbot Project

> **Purpose:** This document is the single source of truth for everything about the Wanda project.
> Future LLMs, developers, and stakeholders should read this first.
>
> **Last updated:** 2026-08-07 (deep GCP research completed)

---

## 1. Project Overview

**Wanda** is an in-house chatbot built on Google's **Agent Development Kit (ADK)**.
It is deployed as a managed service on **Google Cloud Run** and exposes a REST API
that frontends can call to create sessions and run agent conversations.

> **Current web application note (2026-08-25):** The deployed UAT web UI is the
> `wanda-web` Cloud Run service, not the planned `wanda-frontend` service
> described later in this document. It is a small Node.js server plus a single
> HTML page. It proxies Wanda ADK requests and two Conversational Analytics
> agents. See [docs/architecture.md](docs/architecture.md) and
> [docs/deployment.md](docs/deployment.md) before modifying or deploying it.

The goal of this project is to build a **modern, production-quality web frontend**
for Wanda that supports:

- Conversational chat with streaming responses (SSE)
- Conversation history (sidebar)
- File upload / attachment support
- Agent selection (orchestrator "Auto" + sub-agents)
- JumpCloud SSO authentication (planned)
- Dark-themed, responsive UI
- TypeScript codebase (per repo coding standards)

---

## 2. Backend API Specification

### 2.1 Environment URLs

| Environment | Base URL | GCP Project ID | Project Number |
|-------------|----------|----------------|----------------|
| **PROD**    | `https://wanda-adk-service-bot-370161436243.europe-west2.run.app` | `pccw-internal-virtual-agent` | 370161436243 |
| **UAT**     | `https://wanda-adk-service-bot-14417857267.europe-west2.run.app` | `pccw-internal-virt-agent-uat` | 14417857267 |

### 2.2 API Version

- ADK API version: **2.6.2** (verified via `/version` endpoint)
- Language: Python 3.13.14
- Source: [adk.dev/api-reference/rest](https://adk.dev/api-reference/rest/)

### 2.3 Authentication

- **No auth headers required** — verified by live API calls (curl without auth works).
- The API is accessible from the public internet (ingress: all).
- Future: JumpCloud SSO integration may add bearer token / session cookie auth.
- The frontend backend proxy should forward any auth headers if present.

### 2.4 Cloud Run Service Details (UAT)

| Property | Value |
|----------|-------|
| Service name | `wanda-adk-service-bot` |
| Region | `europe-west2` |
| Environment label | `wanda_env: uat` |
| VPC | `eu-uat-wanda-vpc` / `eu-uat-wanda-func-subnet` |
| Min instances | 2 |
| Max instances | 100 |
| Container concurrency | 20 |
| Startup CPU boost | enabled |
| Ingress | all |
| Creator | pbertol@consoleconnect.com |
| Last modifier | jkrayco@consoleconnect.com |

### 2.5 Environment Variables (from Cloud Run service)

These are the env vars configured on the UAT Cloud Run service. They reveal the
agent architecture and data sources:

| Variable | UAT Value | PROD Value |
|----------|-----------|------------|
| `GOOGLE_CLOUD_PROJECT` | `pccw-internal-virt-agent-uat` | `pccw-internal-virtual-agent` |
| `GOOGLE_CLOUD_LOCATION` | `eu` | `eu` |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | `TRUE` |
| `GEMINI_VERSION` | `gemini-3.6-flash` | `gemini-3.6-flash` |
| `JIRA_API_URL` | `https://consoleconnect-sandbox-824.atlassian.net/rest/api/latest` | `https://consoleconnect.atlassian.net/rest/api/latest` |
| `JIRA_AUTH_USERNAME` | `zpaclibar@consoleconnect.com` | `kms-jira@consoleconnect.com` |
| `CONFLUENCE_API_URL` | `https://consoleconnect-sandbox-824.atlassian.net` | (same) |
| `CABLE_EVENT_API_URL` | `.../cable-fault-for-webhook` | `.../cable-event-agent-for-webhook` |
| `REMEDY_TICKET_API_URL` | `.../remedy-api-for-webhook` | `.../remedy-api-for-webhook` |
| `DOCUMENT_AGENT_API_URL` | `.../document-agent-for-webhook` | `.../document-agent-for-webhook` |
| `TICKET_ANALYSIS_API_URL` | `.../ticket-analysis-agent-for-webhook` | `.../ticket-analysis-agent-for-webhook` |
| `WANDA_DLP_SERVICE_API_URL` | `.../wanda-dlp-service` | `.../wanda-dlp-service` |
| `MCP_SERVER_URL` | `https://wanda-mcp-server-14417857267.europe-west2.run.app` | `https://wanda-mcp-server-370161436243.europe-west2.run.app` |
| `COMAROUND_MCP_SERVER_URL` | `https://wanda-mcp-comaround-14417857267.europe-west2.run.app` | (similar) |
| `KNOWLEDGE_SEARCH_API` | `https://knowledge-search-api-14417857267.europe-west2.run.app` | (similar) |
| `BIGQUERY_CABLE_PROJECT_ID` | `pccw-internal-virt-agent-uat` | `pccw-internal-virtual-agent` |
| `BIGQUERY_CABLE_DATASET_ID` | `Testing` | `SubCableEvents` |
| `BIGQUERY_CABLE_TABLE_ID` | `cable_fault_replica` | `cable_fault_replica` |
| `BIGQUERY_TICKET_ANALYSIS_PROJECT_ID` | `pccw-internal-virt-agent-uat` | (same) |
| `BIGQUERY_TICKET_ANALYSIS_DATASET_ID` | `wanda_ds` | `wanda_ds` |
| `BIGQUERY_TICKET_ANALYSIS_TABLE_ID` | `TicketMaster` | `TicketMaster` |
| `BIGQUERY_SHR_PEOPLE_TABLE` | `pccw-internal-virt-agent-uat.GSO.SHRPeople` | (similar) |
| `WANDA_DLP_ALLOWLIST_BIGQUERY_PROJECT_ID` | `pccw-internal-virt-agent-uat` | (similar) |
| `WANDA_DLP_ALLOWLIST_BIGQUERY_DATASET_ID` | `wanda_ds` | `wanda_ds` |
| `WANDA_DLP_ALLOWLIST_BIGQUERY_TABLE_ID` | `dlp_redaction_allowlist` | (same) |
| `WANDA_DLP_ALLOWLIST_BIGQUERY_LOCATION` | `europe-west2` | (same) |
| `WANDA_DLP_ALLOWLIST_CACHE_TTL_SECONDS` | `300` | (same) |
| `CABLE_KNOWN_SYSTEMS` | AAE-1,AAG,ACE,ADC,... (full list of cable systems) | (same) |
| `KNOWLEDGE_RAG_TOP_SCORE_THRESHOLD` | `0.45` | (same) |
| `KMS_IT_OPERATIONS_FOOTER_ENABLED` | `True` | (same) |
| `KMS_IT_OPERATIONS_SPACE_MARKER` | `/spaces/ITOperations/` | (same) |
| `KMS_CONFLUENCE_FALLBACK_ON_LOW_RAG` | `False` | (same) |
| `KMS_INDEXED_STRONG_REQUIRE_QUERY_TERM_OVERLAP` | `True` | (same) |
| `IT_HELPDESK_SLACK_CHANNEL_ID` | `C0B5EKGNZCM` | (same) |
| `WANDA_DLP_PRESERVE_TEXTS` | `true` | (same) |
| `WANDA_DLP_ALLOWLIST_ENABLED` | `true` | (same) |
| `BACKOFF_INIT_DELAY` | `10` | (same) |
| `BACKOFF_ATTEMPTS` | `5` | (same) |
| `BACKOFF_MAX_DELAY` | `60` | (same) |
| `BACKOFF_MULTIPLIER` | `2` | (same) |
| `INSIGHT_USER` | `kms-cnflt@consoleconnect.com` | (same) |
| `WANDA_ENV` | `UAT` | `PROD` |

### 2.6 Endpoints

#### Utility Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check — returns `{"status": "ok"}` |
| `GET`  | `/version` | API version — returns `{"version": "2.6.2", "language": "python", "language_version": "3.13.14"}` |
| `GET`  | `/list-apps` | List all agent applications — returns `["wanda_chatbot"]` |
| `GET`  | `/apps/{app_name}/app-info` | Get ADK app info — **returns 500 Internal Server Error** for wanda_chatbot |

#### Session Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | Create session with specific ID |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | Get session details |
| `DELETE` | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | Delete session |
| `PATCH` | `/apps/{app_name}/users/{user_id}/sessions/{session_id}` | Update session |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions` | List all sessions for a user |
| `POST` | `/apps/{app_name}/users/{user_id}/sessions` | Create session (auto-generated ID) |

#### Agent Execution

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/run` | Execute agent — returns all events as a JSON array (non-streaming) |
| `POST` | `/run_sse` | Execute agent — streams events as Server-Sent Events (SSE) |

#### Artifact Management (within a session)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts` | Save artifact |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts` | List artifact names |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}` | Load artifact |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}/versions` | List artifact versions |
| `GET`  | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}/versions/{version_id}` | Load specific artifact version |
| `DELETE` | `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name}` | Delete artifact |

#### Memory Management

| Method | Path | Description |
|--------|------|-------------|
| `PATCH` | `/apps/{app_name}/users/{user_id}/memory` | Patch memory |

---

## 3. Request / Response Schemas

### 3.1 RunAgentRequest (used by `/run` and `/run_sse`)

```json
{
  "app_name": "wanda_chatbot",
  "user_id": "string",
  "session_id": "string",
  "new_message": {
    "role": "user",
    "parts": [
      { "text": "Hello, what can you help with?" }
    ]
  },
  "streaming": true,
  "state_delta": {},
  "function_call_event_id": null,
  "invocation_id": null,
  "custom_metadata": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `app_name` | string | No (defaults to server default) | The agent application name. For Wanda: `wanda_chatbot` |
| `user_id` | string | **Yes** | Unique user identifier |
| `session_id` | string | **Yes** | Unique session identifier |
| `new_message` | Content | No | The user's message (role + parts) |
| `streaming` | boolean | No (default: `false`) | Enable token-level streaming |
| `state_delta` | object | No | State changes to apply |
| `function_call_event_id` | string | No | For long-running function resume |
| `invocation_id` | string | No | For resume long-running functions |
| `custom_metadata` | object | No | Custom metadata for the run |

### 3.2 Content (Google GenAI types)

```json
{
  "role": "user",
  "parts": [
    { "text": "message text" }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | `"user"`, `"model"`, or `"function"` |
| `parts` | array of Part | Message parts |

### 3.3 Part

```json
{
  "text": "string",
  "functionCall": { ... },
  "functionResponse": { ... },
  "fileData": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Text content |
| `functionCall` | FunctionCall | A function/tool call |
| `functionResponse` | FunctionResponse | A function/tool response |
| `fileData` | FileData | File attachment data |

### 3.4 Event (actual response from `/run` and `/run_sse`)

Verified by live API call. The actual Event object has these fields:

```json
{
  "modelVersion": "gemini-3.6-flash",
  "content": {
    "parts": [
      { "text": "Agent response text..." }
    ],
    "role": "model"
  },
  "partial": true,
  "finishReason": "STOP",
  "usageMetadata": {
    "candidatesTokenCount": 10,
    "candidatesTokensDetails": [{"modality": "TEXT", "tokenCount": 10}],
    "promptTokenCount": 4663,
    "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 4663}],
    "thoughtsTokenCount": 128,
    "totalTokenCount": 4801,
    "trafficType": "ON_DEMAND"
  },
  "invocationId": "e-10963659-1ca5-4a50-bc23-e447e87d5dbe",
  "author": "WandaCoordinator",
  "actions": {
    "stateDelta": {},
    "artifactDelta": {},
    "requestedAuthConfigs": {},
    "requestedToolConfirmations": {}
  },
  "nodeInfo": {
    "path": "WandaCoordinator@1"
  },
  "longRunningToolIds": [],
  "id": "7267a6b6-e8fe-4c35-a6ce-e97ed6b4c76f",
  "timestamp": 1786075485.4535346
}
```

| Field | Type | Description |
|-------|------|-------------|
| `modelVersion` | string | LLM model used (e.g., `gemini-3.6-flash`) |
| `content` | Content | The content of the event (may be null for tool events) |
| `partial` | boolean | **SSE only** — `true` means more tokens are coming for this event |
| `finishReason` | string | Why generation stopped (e.g., `STOP`, `MAX_TOKENS`) |
| `usageMetadata` | object | Token usage stats (only on final event) |
| `invocationId` | string | Unique ID for the invocation |
| `author` | string | Agent name (e.g., `WandaCoordinator`) |
| `actions` | EventActions | Actions taken by the event |
| `nodeInfo` | object | Agent node info — `path` field shows agent name + instance (e.g., `WandaCoordinator@1`) |
| `longRunningToolIds` | array | IDs of long-running tools |
| `id` | string | Unique event ID |
| `timestamp` | number | Unix timestamp with microseconds |

### 3.5 EventActions

| Field | Type | Description |
|-------|------|-------------|
| `artifactDelta` | `{ [key: string]: number }` | Artifact updates (key=filename, value=version) |
| `escalate` | boolean | Agent escalating to higher-level agent |
| `requestedAuthConfigs` | `{ [key: string]: AuthConfig }` | Auth configs requested by tool responses |
| `requestedToolConfirmations` | `{ [key: string]: ToolConfirmation }` | Tool confirmations requested |
| `skipSummarization` | boolean | Skip model summarization of function response |
| `stateDelta` | `{ [key: string]: unknown }` | State changes to apply to session |
| `transferToAgent` | string | Transfer to specified agent |

### 3.6 `/run` Response

Returns a **JSON array of Event objects**:

```json
[
  {
    "modelVersion": "gemini-3.6-flash",
    "content": { "parts": [{ "functionCall": { "name": "get_platform", "args": {} } }], "role": "model" },
    "finishReason": "STOP",
    "invocationId": "e-...",
    "author": "WandaCoordinator",
    "actions": { "stateDelta": {}, "artifactDelta": {}, "requestedAuthConfigs": {}, "requestedToolConfirmations": {} },
    "nodeInfo": { "path": "WandaCoordinator@1" },
    "longRunningToolIds": [],
    "id": "...",
    "timestamp": 1786075485.4535346
  },
  {
    "content": { "parts": [{ "functionResponse": { "name": "get_platform", "response": { "status": "success", "platform": "web" } } }], "role": "user" },
    "invocationId": "e-...",
    "author": "WandaCoordinator",
    "actions": { "stateDelta": { ...glossary... }, "artifactDelta": {}, "requestedAuthConfigs": {}, "requestedToolConfirmations": {} },
    "nodeInfo": { "path": "WandaCoordinator@1" },
    "id": "...",
    "timestamp": 1786075577.8259676
  },
  {
    "modelVersion": "gemini-3.6-flash",
    "content": { "parts": [{ "text": "Hello! I'm Wanda, your concierge for Console Connect..." }], "role": "model" },
    "finishReason": "STOP",
    "invocationId": "e-...",
    "author": "WandaCoordinator",
    "actions": { "stateDelta": {}, "artifactDelta": {}, "requestedAuthConfigs": {}, "requestedToolConfirmations": {} },
    "nodeInfo": { "path": "WandaCoordinator@1" },
    "longRunningToolIds": [],
    "id": "...",
    "timestamp": 1786075580.2877743
  }
]
```

### 3.7 `/run_sse` Response (Streaming)

Returns **Server-Sent Events (SSE)**. Each event is prefixed with `data: ` followed by a JSON Event object, terminated by two newlines:

```
data: {"modelVersion":"gemini-3.6-flash","content":{"parts":[{"functionCall":{"id":"ZfpGj7XL","args":{},"name":"get_platform"}}],"role":"model"},"partial":true,"usageMetadata":{"trafficType":"ON_DEMAND"},"invocationId":"e-...","author":"WandaCoordinator","actions":{"stateDelta":{},"artifactDelta":{},"requestedAuthConfigs":{},"requestedToolConfirmations":{}},"nodeInfo":{"path":"WandaCoordinator@1"},"longRunningToolIds":[],"id":"...","timestamp":1786075575.0049176}

data: {"modelVersion":"gemini-3.6-flash","content":{"parts":[{"text":"Hello!"}],"role":"model"},"partial":true,"usageMetadata":{"trafficType":"ON_DEMAND"},"invocationId":"e-...","author":"WandaCoordinator","actions":{"stateDelta":{},"artifactDelta":{},"requestedAuthConfigs":{},"requestedToolConfirmations":{}},"nodeInfo":{"path":"WandaCoordinator@1"},"longRunningToolIds":[],"id":"...","timestamp":1786075580.2877743}

data: {"modelVersion":"gemini-3.6-flash","content":{"parts":[{"text":" I'm Wanda, your concierge for Console Connect. How can I assist you today?"}],"role":"model"},"partial":true,"usageMetadata":{"trafficType":"ON_DEMAND"},"invocationId":"e-...","author":"WandaCoordinator","actions":{"stateDelta":{},"artifactDelta":{},"requestedAuthConfigs":{},"requestedToolConfirmations":{}},"nodeInfo":{"path":"WandaCoordinator@1"},"longRunningToolIds":[],"id":"...","timestamp":1786075581.1823}
```

Key SSE observations:
- `partial: true` means more tokens are coming for the same event (same `id`)
- `partial: false` or absent means the event is complete
- Text tokens stream incrementally — each SSE event may contain a partial text chunk
- Function calls appear as `functionCall` in `content.parts`
- Function responses appear as `functionResponse` in `content.parts` with `role: "user"`
- The `stateDelta` in `actions` can contain session state like the acronym glossary

### 3.8 CreateSessionRequest

The session creation endpoint (`POST /apps/{app_name}/users/{user_id}/sessions/{session_id}`)
accepts a body with platform-specific metadata:

```json
{
  "platform": "web",
  "slackChatInterface": "DM"
}
```

**Verified response:**
```json
{
  "id": "test-session-1786075484",
  "appName": "wanda_chatbot",
  "userId": "testuser",
  "state": {
    "platform": "web",
    "slackChatInterface": "DM"
  },
  "events": [],
  "lastUpdateTime": 0.0
}
```

> **Note:** The `platform` field can be set to `"web"` for web frontend. The `slackChatInterface` field is still required but its value doesn't matter for web.

---

## 4. Streaming vs Non-Streaming

### Non-Streaming (`/run`)

- **How it works:** The client sends a request, the server processes the entire agent
  run, and returns **all events at once** as a JSON array.
- **Response time:** The client waits until the agent finishes all work (including
  tool calls, sub-agent delegation, etc.) before receiving any data.
- **User experience:** The user sees a typing indicator, then suddenly the full
  response appears all at once.
- **Pros:** Simple to implement, easy to retry, no connection management needed.
- **Cons:** Poor UX for long-running agent tasks — user has no feedback during
  processing.

### Streaming (`/run_sse`)

- **How it works:** The client sends a request with `"streaming": true`, and the
  server sends **events as they are generated** using Server-Sent Events (SSE).
- **Response time:** The client receives events incrementally — text tokens stream
  in real-time, tool calls are visible as they happen.
- **User experience:** The response appears word-by-word (like ChatGPT), giving
  immediate feedback that the agent is working.
- **Pros:** Much better UX, especially for long-running agent tasks. Users see
  progress in real-time.
- **Cons:** More complex to implement (SSE parsing, connection management,
  reconnection logic).

### Recommendation

**Use streaming (`/run_sse`) for the Wanda frontend.** Chatbots benefit greatly
from streaming because:
1. Users get immediate feedback that their message was received.
2. Long-running agent tasks (tool calls, sub-agent delegation) show progress.
3. The experience feels more natural and responsive.

The non-streaming `/run` endpoint can be used as a fallback if SSE fails.

---

## 5. Wanda Agent Architecture

### Orchestrator Agent: WandaCoordinator

The top-level orchestrator agent (verified via live API call — `author: "WandaCoordinator"`,
`nodeInfo.path: "WandaCoordinator@1"`).

**Agent greeting (verified):**
> "Hello! I'm Wanda, your concierge for Console Connect. How can I assist you today?
> I can help you look up Remedy or Jira tickets, search internal documentation and
> Confluence, check cable events, analyze documents, or assist with ticket analytics."

**Model:** `gemini-3.6-flash` (via Vertex AI)

### Sub-Agents (inferred from Cloud Run env vars)

The orchestrator delegates to sub-agents. Based on the environment variables
configured on the Cloud Run service, the following sub-agents/tools are available:

| Sub-Agent / Tool | Env Var | Description |
|------------------|---------|-------------|
| **Cable Fault Agent** | `CABLE_EVENT_API_URL` | Checks cable events and faults |
| **Remedy Ticket Agent** | `REMEDY_TICKET_API_URL` | Looks up Remedy tickets |
| **Document Agent** | `DOCUMENT_AGENT_API_URL` | Analyzes documents (PDF, etc.) |
| **Ticket Analysis Agent** | `TICKET_ANALYSIS_API_URL` | Ticket analytics and reporting |
| **DLP Service** | `WANDA_DLP_SERVICE_API_URL` | Data loss prevention / redaction |
| **MCP Server** | `MCP_SERVER_URL` | Model Context Protocol server |
| **Comaround MCP** | `COMAROUND_MCP_SERVER_URL` | Comaround knowledge integration |
| **Knowledge Search** | `KNOWLEDGE_SEARCH_API` | Knowledge base search (RAG) |
| **Confluence** | `CONFLUENCE_API_URL` | Confluence documentation search |
| **Jira** | `JIRA_API_URL` | Jira ticket management |
| **BigQuery** | `BIGQUERY_*` vars | Data warehouse queries (TicketMaster, SHRPeople, etc.) |

### Agent Selection

The frontend should provide a dropdown or selector that allows users to choose:
1. **Auto** (default) — Let the `WandaCoordinator` orchestrator decide which sub-agent to use
2. **Specific sub-agents** — Route directly to a specific agent (if the ADK API supports
   targeting specific agents)

> **Note:** The ADK API currently only exposes `wanda_chatbot` as a single app.
> The sub-agent routing happens internally within the orchestrator. The frontend
> may not be able to directly select sub-agents unless the ADK API supports
> agent-level routing. This needs to be confirmed with the development team.

### Acronym Glossary

The WandaCoordinator loads an acronym glossary from a Google Sheet
(`https://docs.google.com/spreadsheets/d/1xNGQb4n0ncp2yuHkkWODo_X7sUJ2J9tZ_REydNkfzSA/edit`)
and includes it in the session state. The glossary contains 101 entries covering
telecom, networking, and Console Connect terminology (e.g., CC=Console Connect,
GSOC=Global Services Operations Center, MTTR=Mean Time To Restore, etc.).

---

## 6. Frontend Architecture

### Overview

The frontend will be a **standalone web application** that communicates with the
Wanda ADK API through a **backend proxy** (to avoid CORS and keep API URLs secret).

### Architecture Diagram

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│   User Browser  │────▶│  Frontend Proxy  │────▶│  Wanda ADK API       │
│  (HTML/CSS/TS)  │     │  (Node.js/       │     │  (Cloud Run)         │
│                 │◀────│   Express/TS)    │◀────│  https://wanda-...  │
└─────────────────┘     └──────────────────┘     └──────────────────────┘
                              │
                              ▼
                        ┌─────────────┐
                        │  JumpCloud  │
                        │  SSO        │
                        └─────────────┘
```

### Why a Backend Proxy?

1. **CORS avoidance** — The ADK API may not have CORS headers configured for
   browser access.
2. **API URL secrecy** — The ADK API URL should not be exposed in client-side code.
3. **Auth handling** — Future JumpCloud SSO integration can be handled server-side.
4. **Request/response transformation** — The proxy can transform ADK API responses
   into a frontend-friendly format.
5. **SSE proxying** — The proxy can forward SSE streams to the browser.

### Tech Stack

> **Important:** The repo coding standards (`KnowledgeBase/standards/coding.md`)
> require **TypeScript only**, strict types, no `any`, JSDoc, and Jest unit tests.

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Frontend** | TypeScript + Vite | Build tool, HMR, type safety, modern JS |
| **Backend Proxy** | Node.js + Express + TypeScript | Type safety, matches existing patterns |
| **Containerization** | Docker (Node 20 Alpine) | Consistent deployment |
| **Hosting** | Google Cloud Run | Serverless, scales to zero, HTTPS auto-provisioned |
| **Styling** | CSS Custom Properties (CSS variables) | No framework dependency, easy theming |
| **Testing** | Jest | Per coding standards |
| **CI/CD** | Cloud Build | Automated builds and deployments |

### Project Structure

```
Wanda/
├── README.md                    # This file — project documentation
├── docker-compose.yml           # Local development
├── frontend/                    # Frontend application (TypeScript + Vite)
│   ├── index.html               # Main HTML page
│   ├── vite.config.ts           # Vite config
│   ├── tsconfig.json            # TypeScript config
│   ├── package.json
│   ├── src/
│   │   ├── main.ts              # App entry point
│   │   ├── App.ts               # Main app component
│   │   ├── api.ts               # API client (SSE streaming)
│   │   ├── ui.ts                # UI rendering utilities
│   │   ├── markdown.ts          # Markdown rendering
│   │   ├── utils.ts             # Utility functions (UUID, localStorage, etc.)
│   │   ├── types.ts             # TypeScript type definitions
│   │   └── styles/
│   │       └── style.css        # All styles (dark theme)
│   └── assets/
│       └── favicon.ico
├── backend/                     # Backend proxy server (TypeScript)
│   ├── src/
│   │   ├── server.ts            # Express server
│   │   ├── routes/
│   │   │   ├── chat.ts          # /api/chat (SSE proxy)
│   │   │   ├── session.ts       # /api/session
│   │   │   ├── config.ts        # /api/config
│   │   │   └── upload.ts        # /api/upload
│   │   └── middleware/
│   │       └── auth.ts          # Auth middleware (future)
│   ├── package.json
│   ├── tsconfig.json
│   ├── Dockerfile
│   ├── .dockerignore
│   └── .env.example
├── agents/                      # Agent configuration and documentation
│   └── README.md                # Agent descriptions and capabilities
├── docs/                        # Additional documentation
│   ├── api-reference.md         # ADK API reference
│   ├── deployment.md            # Deployment guide
│   └── architecture.md          # Architecture decisions
└── tests/                       # Jest unit tests
    ├── frontend/
    └── backend/
```

---

## 7. Key Features

### 7.1 Chat Interface

- Dark-themed chat window (matching existing project style)
- User and bot message bubbles
- Typing indicator with animated dots
- Suggestion chips for common questions
- Auto-scrolling to latest message
- Responsive layout (desktop + mobile)

### 7.2 Streaming Responses

- SSE connection to `/run_sse` via backend proxy
- Token-by-token text rendering (partial events)
- Tool call visibility (showing when agent is calling tools)
- Graceful fallback to non-streaming `/run` if SSE fails
- Reconnection logic for dropped connections

### 7.3 Conversation History

- Sidebar showing past conversations
- Click to load previous conversation
- New conversation button
- Local storage for session persistence
- Session management via ADK API

### 7.4 File Upload

- Attach files to messages
- Support for common file types (PDF, images, text, CSV)
- File preview/thumbnail
- Upload via ADK artifact API

### 7.5 Agent Selection

- Dropdown to select agent:
  - **Auto** (WandaCoordinator orchestrator) — default
  - Sub-agents (if API supports direct routing)
- Agent descriptions on hover
- Visual indicator of which agent is active

### 7.6 Authentication (Planned)

- JumpCloud SSO integration
- OIDC flow
- Session management via cookies
- User identity passed to ADK API as `user_id`

---

## 8. GCP Hosting

### Cloud Run (Recommended)

The Wanda ADK API is already deployed on Cloud Run in `europe-west2`. The frontend
should be deployed to the same region for low latency.

**Existing Cloud Run services in UAT (`pccw-internal-virt-agent-uat`):**
- `wanda-adk-service-bot` — main ADK API
- `wanda-adk-service-bot-dev` — dev version
- `wanda-adk-slack-webhook` — Slack webhook
- `wanda-mcp-server` — MCP server
- `wanda-mcp-comaround` — Comaround MCP
- `wanda-voicebot` — Voicebot
- `wanda-dlp-service` — DLP service
- `knowledge-search-api` — Knowledge search
- `knowledge-ingestion` — Knowledge ingestion
- `ticket-agent-function` / `ticket-agent-function-uat` — Ticket agent
- `ticket-analysis-agent-for-webhook` — Ticket analysis
- `ticket-helper` — Ticket helper
- `document-agent-for-webhook` / `document-agent-function` — Document agent
- `cable-fault-for-webhook` — Cable fault agent
- `remedy-api-for-webhook` — Remedy API
- `confluence-chat` — Confluence chat (the experiment)
- `ai-strategy-app` — AI Strategy app
- `slack-webhook` / `slack-interactive-webhook` — Slack webhooks
- `email-triage-api` — Email triage
- Various data sync functions

**Deployment target:**
- Project: `pccw-internal-virt-agent-uat` (UAT) / `pccw-internal-virtual-agent` (PROD)
- Region: `europe-west2`
- Service name: `wanda-frontend` (new service)
- VPC: `eu-uat-wanda-vpc` (for internal access to other services)

### Why Cloud Run?

1. **Serverless** — scales to zero, pay per use
2. **HTTPS auto-provisioned** with managed certificates
3. **Same platform** as the ADK API (consistency)
4. **Can serve static files AND run backend proxy** in same container
5. **Atomic deployments** and rollbacks
6. **Integrates with Cloud Build** for CI/CD
7. **VPC access** — can reach internal services via VPC connector

---

## 9. Development Workflow

### Local Development

```bash
# 1. Clone the repo
git clone <repo-url>
cd Wanda

# 2. Set up environment
cp backend/.env.example backend/.env
# Edit .env with your ADK API URL

# 3. Install dependencies
cd frontend && npm install
cd ../backend && npm install

# 4. Run with Docker Compose (for backend proxy)
docker-compose up

# 5. Run frontend dev server
cd frontend && npm run dev
# Open http://localhost:5173
```

### Deployment

```bash
# 1. Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/pccw-internal-virt-agent-uat/wanda-frontend

# 2. Deploy to Cloud Run
gcloud run deploy wanda-frontend \
  --image gcr.io/pccw-internal-virt-agent-uat/wanda-frontend \
  --platform managed \
  --region europe-west2 \
  --set-env-vars ADK_API_URL=https://wanda-adk-service-bot-14417857267.europe-west2.run.app
```

---

## 10. Open Questions / TODO

- [x] **GCP project IDs** — UAT: `pccw-internal-virt-agent-uat`, PROD: `pccw-internal-virtual-agent`
- [x] **Cloud Run region** — `europe-west2`
- [x] **ADK API auth** — No auth required (verified by live API call)
- [x] **Orchestrator agent name** — `WandaCoordinator`
- [x] **Sub-agent names** — Inferred from env vars (Cable Fault, Remedy, Document, Ticket Analysis, DLP, MCP, Comaround, Knowledge Search, Confluence, Jira)
- [x] **Agent greeting** — "Hello! I'm Wanda, your concierge for Console Connect..."
- [x] **Model** — `gemini-3.6-flash` via Vertex AI
- [x] **ADK API version** — 2.6.2
- [ ] **Agent selection** — Confirm if ADK API supports direct sub-agent routing
- [ ] **File upload** — Confirm artifact API works for file uploads
- [ ] **JumpCloud SSO** — Confirm integration requirements
- [ ] **Custom domain** — Confirm domain and SSL requirements
- [ ] **TypeScript build** — Confirm Vite + ts-node setup is acceptable

---

## 11. References

- ADK API Documentation: https://adk.dev/api-reference/rest/
- ADK API Server Guide: https://adk.dev/runtime/api-server/
- ADK Python Source: https://github.com/google/adk-python
- GCP Static Hosting Comparison: https://til.cafe/blog/2024/deciding-how-to-host-a-static-site-on-google-cloud/
- JumpCloud SSO: https://jumpcloud.com/support/sso-with-oidc
- Wanda API Spec: `KnowledgeBase/wandaconnect.txt`
- Coding Standards: `KnowledgeBase/standards/coding.md`
- Persona: `KnowledgeBase/persona/technical-caveman.md`
