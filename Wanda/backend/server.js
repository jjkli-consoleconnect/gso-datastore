/* Wanda Backend Proxy Server
   Handles the main Wanda chat and the secondary data-analytics agent used by the dashboard.
*/

const express = require("express");
const { GoogleAuth } = require("google-auth-library");

const app = express();
const PORT = process.env.PORT || 8080;
const ADK_API_URL = process.env.ADK_API_URL || "https://wanda-adk-service-bot-14417857267.europe-west2.run.app";
const ADK_APP_NAME = process.env.ADK_APP_NAME || "wanda_chatbot";
const DATA_AGENT_PATH = process.env.DATA_AGENT_PATH || "projects/pccw-internal-virt-agent-uat/locations/global/dataAgents/gso-center-operations-data-analayst";
const DATA_AGENT_PARENT = "projects/pccw-internal-virt-agent-uat/locations/global";

app.disable("x-powered-by");
app.use(express.json({ limit: "10mb" }));
app.use(express.static("../frontend"));

app.get("/health", (req, res) => res.json({ status: "ok" }));

app.get("/api/config", (req, res) => {
  res.json({
    adkApiUrl: ADK_API_URL,
    adkAppName: ADK_APP_NAME,
    dataAgentPath: DATA_AGENT_PATH,
  });
});

app.post("/api/wanda/apps/:appName/users/:userId/sessions/:sessionId", async (req, res) => {
  const { appName, userId, sessionId } = req.params;

  try {
    const response = await fetch(
      `${ADK_API_URL}/apps/${encodeURIComponent(appName)}/users/${encodeURIComponent(userId)}/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body || {}),
      }
    );

    const payload = await response.text();
    return res.status(response.status).type("application/json").send(payload);
  } catch (error) {
    console.error("Wanda session proxy error:", error);
    return res.status(500).json({ error: "Failed to create Wanda session" });
  }
});

app.post("/api/wanda/run", async (req, res) => {
  const { app_name, user_id, session_id, new_message } = req.body || {};

  if (!user_id || !session_id || !new_message) {
    return res.status(400).json({ error: "Missing required Wanda run fields" });
  }

  try {
    const response = await fetch(`${ADK_API_URL}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app_name: app_name || ADK_APP_NAME,
        user_id,
        session_id,
        new_message,
      }),
    });

    const payload = await response.text();
    const contentType = response.headers.get("content-type") || "";

    if (!response.ok) {
      return res.status(response.status).send(payload || `Wanda request failed (${response.status})`);
    }

    if (contentType.includes("application/json")) {
      return res.type("application/json").send(payload);
    }

    return res.type("application/json").send(payload);
  } catch (error) {
    console.error("Wanda proxy error:", error);
    return res.status(500).json({ error: "Failed to reach Wanda ADK backend" });
  }
});

function extractAnalyticsText(payload) {
  if (!payload) return "";

  if (typeof payload.text === "string" && payload.text.trim()) return payload.text.trim();
  if (typeof payload.reply === "string" && payload.reply.trim()) return payload.reply.trim();
  if (typeof payload.message === "string" && payload.message.trim()) return payload.message.trim();

  if (payload.response) return extractAnalyticsText(payload.response);

  if (Array.isArray(payload.candidates)) {
    const collected = payload.candidates
      .map((candidate) => {
        if (typeof candidate?.content === "string") return candidate.content;
        if (candidate?.text) return candidate.text;
        if (candidate?.content?.parts) {
          return candidate.content.parts
            .map((part) => part.text || part.content || "")
            .filter(Boolean)
            .join("\n");
        }
        return "";
      })
      .filter(Boolean);

    if (collected.length) return collected.join("\n\n");
  }

  if (payload.content?.parts) {
    const parts = payload.content.parts
      .map((part) => part.text || part.content || "")
      .filter(Boolean);
    if (parts.length) return parts.join("\n");
  }

  if (typeof payload === "string") return payload;

  return "";
}

app.post("/api/data-agent/chat", async (req, res) => {
  const message = req.body?.message || req.body?.query;
  if (!message || !String(message).trim()) {
    return res.status(400).json({ error: "Missing message text" });
  }

  try {
    const auth = new GoogleAuth({
      scopes: ["https://www.googleapis.com/auth/cloud-platform"],
    });

    const client = await auth.getClient();
    const accessToken = await client.getAccessToken();
    const bearerToken = accessToken.token;

    const createConversationResponse = await fetch(
      `https://geminidataanalytics.googleapis.com/v1/${DATA_AGENT_PARENT}/conversations`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${bearerToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ agent: DATA_AGENT_PATH }),
      }
    );

    const createConversationText = await createConversationResponse.text();
    if (!createConversationResponse.ok) {
      return res.status(createConversationResponse.status).json({
        error: "Failed to create data agent conversation",
        details: createConversationText,
      });
    }

    const conversation = JSON.parse(createConversationText || "{}");
    const conversationName = conversation?.name;
    if (!conversationName) {
      return res.status(502).json({ error: "Data agent did not return a conversation name" });
    }

    const chatResponse = await fetch(
      `https://geminidataanalytics.googleapis.com/v1/${conversationName}:chat`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${bearerToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: message }),
      }
    );

    const chatResponseText = await chatResponse.text();
    if (!chatResponse.ok) {
      return res.status(chatResponse.status).json({
        error: "Failed to send query to data agent",
        details: chatResponseText,
      });
    }

    const chatPayload = JSON.parse(chatResponseText || "{}");
    const text = extractAnalyticsText(chatPayload);

    return res.json({
      text: text || "The analytics agent returned no response.",
    });
  } catch (error) {
    console.error("Analytics agent proxy error:", error);
    return res.status(500).json({
      error: "Failed to connect the dashboard data agent",
      details: error.message,
    });
  }
});

app.listen(PORT, () => console.log(`Wanda backend listening on port ${PORT}`));
