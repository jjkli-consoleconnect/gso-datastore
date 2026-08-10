/* Wanda Backend Proxy Server
   TODO: Implement Express server that proxies requests to the Wanda ADK API

   Endpoints to implement:
   - GET  /health           — health check
   - GET  /api/config       — return frontend config (ADK API URL, app name)
   - POST /api/session      — create a new session
   - POST /api/chat         — proxy to ADK /run_sse (streaming)
   - POST /api/chat/sync    — proxy to ADK /run (non-streaming fallback)
   - GET  /api/history      — get conversation history
   - POST /api/upload       — upload file as artifact

   Environment variables:
   - ADK_API_URL           — Wanda ADK API base URL
   - ADK_APP_NAME          — Agent app name (default: wanda_chatbot)
   - PORT                  — Server port (default: 8080)
   - JUMPCLOUD_CLIENT_ID   — For future SSO integration
   - JUMPCLOUD_CLIENT_SECRET — For future SSO integration
*/

const express = require("express");
const app = express();
const PORT = process.env.PORT || 8080;

app.disable("x-powered-by");
app.use(express.json({ limit: "10mb" }));
app.use(express.static("../frontend"));

app.get("/health", (req, res) => res.json({ status: "ok" }));

app.listen(PORT, () => console.log(`Wanda backend listening on port ${PORT}`));
