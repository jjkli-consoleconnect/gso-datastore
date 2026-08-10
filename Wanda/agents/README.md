# Wanda Agents

## Architecture: Routing Agent + Sub-Agents

The Wanda ADK API exposes a single app: `wanda_chatbot`. This app contains a
**routing orchestrator agent** (`WandaCoordinator`) that determines which
**sub-agent** to call based on user intent.

### How It Works

```
User Query
    │
    ▼
WandaCoordinator (orchestrator / "Auto")
    │
    ├──▶ Cable Fault Agent (CABLE_EVENT_API_URL)
    ├──▶ Remedy Ticket Agent (REMEDY_TICKET_API_URL)
    ├──▶ Document Agent (DOCUMENT_AGENT_API_URL)
    ├──▶ Ticket Analysis Agent (TICKET_ANALYSIS_API_URL)
    ├──▶ DLP Service (WANDA_DLP_SERVICE_API_URL)
    ├──▶ MCP Server (MCP_SERVER_URL)
    ├──▶ Comaround MCP (COMAROUND_MCP_SERVER_URL)
    ├──▶ Knowledge Search (KNOWLEDGE_SEARCH_API)
    ├──▶ Confluence (CONFLUENCE_API_URL)
    └─── Jira (JIRA_API_URL)
```

### Frontend Agent Selection

The frontend should provide:

1. **Auto** (default) — Sends query to `WandaCoordinator`. The orchestrator
   analyzes user intent and routes to the appropriate sub-agent automatically.

2. **Direct sub-agent selection** — Users can bypass the orchestrator and
   route directly to a specific sub-agent. This requires the frontend to
   call the sub-agent's Cloud Run service directly (not through the ADK API).

> **Note:** The ADK API (`/run`, `/run_sse`) only accepts `app_name: "wanda_chatbot"`.
> There is no agent-level routing parameter in the API. Direct sub-agent routing
> would require the frontend backend proxy to call sub-agent services directly.

### Sub-Agent Details

| Agent | Cloud Run Service | Env Var | Description |
|-------|-------------------|---------|-------------|
| **WandaCoordinator** | `wanda-adk-service-bot` | (orchestrator) | Top-level routing agent. Determines user intent and delegates to sub-agents. |
| **Cable Fault Agent** | `cable-fault-for-webhook` | `CABLE_EVENT_API_URL` | Checks cable events and faults. Uses BigQuery `SubCableEvents` dataset. |
| **Remedy Ticket Agent** | `remedy-api-for-webhook` | `REMEDY_TICKET_API_URL` | Looks up Remedy (Tier 1) tickets. |
| **Document Agent** | `document-agent-for-webhook` | `DOCUMENT_AGENT_API_URL` | Analyzes documents (PDF, etc.). |
| **Ticket Analysis Agent** | `ticket-analysis-agent-for-webhook` | `TICKET_ANALYSIS_API_URL` | Ticket analytics and reporting. Uses BigQuery `wanda_ds.TicketMaster`. |
| **DLP Service** | `wanda-dlp-service` | `WANDA_DLP_SERVICE_API_URL` | Data loss prevention / redaction. Uses BigQuery `wanda_ds.dlp_redaction_allowlist`. |
| **MCP Server** | `wanda-mcp-server` | `MCP_SERVER_URL` | Model Context Protocol server. |
| **Comaround MCP** | `wanda-mcp-comaround` | `COMAROUND_MCP_SERVER_URL` | Comaround knowledge integration. |
| **Knowledge Search** | `knowledge-search-api` | `KNOWLEDGE_SEARCH_API` | Knowledge base search (RAG). Threshold: 0.45. |
| **Confluence** | (external) | `CONFLUENCE_API_URL` | Confluence documentation search. |
| **Jira** | (external) | `JIRA_API_URL` | Jira ticket management. |

### Agent Greeting

The WandaCoordinator's default greeting (verified via live API call):

> "Hello! I'm Wanda, your concierge for Console Connect. How can I assist you today?
> I can help you look up Remedy or Jira tickets, search internal documentation and
> Confluence, check cable events, analyze documents, or assist with ticket analytics."

### Model

- **LLM:** `gemini-3.6-flash` (via Vertex AI)
- **ADK version:** 2.6.2
- **Language:** Python 3.13.14

### Acronym Glossary

The WandaCoordinator loads an acronym glossary from a Google Sheet:
`https://docs.google.com/spreadsheets/d/1xNGQb4n0ncp2yuHkkWODo_X7sUJ2J9tZ_REydNkfzSA/edit`

Contains 101 entries covering telecom, networking, and Console Connect terminology.
Loaded into session state on first interaction.
