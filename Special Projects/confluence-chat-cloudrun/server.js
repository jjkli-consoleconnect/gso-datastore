const express = require("express");
const https = require("https");

const app = express();

const PORT = process.env.PORT || 8080;
const GEMINI_API_KEY = (process.env.GEMINI_API_KEY || "").trim();
const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-2.5-flash";
const CONFLUENCE_API_TOKEN = (process.env.CONFLUENCE_API_TOKEN || "").trim();
const CONFLUENCE_EMAIL = (process.env.CONFLUENCE_EMAIL || "").trim();
const CONFLUENCE_BASE = "https://consoleconnect.atlassian.net/wiki";
const CONFLUENCE_SPACE = "WNDA";
const CONFLUENCE_ORIGIN = process.env.CONFLUENCE_ORIGIN || "";

app.disable("x-powered-by");
app.use(express.json({ limit: "2mb" }));
app.use(express.static("public"));

app.use((req, res, next) => {
  const frameAncestors = ["'self'"];
  if (CONFLUENCE_ORIGIN) frameAncestors.push(CONFLUENCE_ORIGIN);
  res.setHeader(
    "Content-Security-Policy",
    `frame-ancestors ${frameAncestors.join(" ")}`
  );
  res.setHeader("X-Content-Type-Options", "nosniff");
  next();
});

app.get("/healthz", (req, res) => res.json({ status: "ok" }));

function getSmallTalkResponse(question) {
  const normalized = question.toLowerCase().trim().replace(/[!?.,]+$/g, "");

  if (["hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening"].includes(normalized)) {
    return "Hi. Ask me anything about the WNDA Confluence space, such as architecture, agents, access validation, or security.";
  }

  if (["thanks", "thank you", "thx", "cheers"].includes(normalized)) {
    return "You're welcome. If you want, ask another question about the WNDA documentation.";
  }

  if (["bye", "goodbye", "see ya", "see you"].includes(normalized)) {
    return "Bye. Come back if you need anything from the WNDA knowledge base.";
  }

  return null;
}

function extractConfluenceText(rawHtml) {
  return rawHtml
    .replace(/<ac:image[\s\S]*?<\/ac:image>/gi, " ")
    .replace(/<ac:structured-macro[^>]*>[\s\S]*?<ac:plain-text-body><!\[CDATA\[([\s\S]*?)\]\]><\/ac:plain-text-body>[\s\S]*?<\/ac:structured-macro>/gi, "\n$1\n")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/gi, "\n$1\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>|<\/div>|<\/section>|<\/article>|<\/h[1-6]>|<\/tr>/gi, "\n")
    .replace(/<li[^>]*>/gi, "\n- ")
    .replace(/<\/li>/gi, "")
    .replace(/<\/td>\s*<td[^>]*>/gi, " | ")
    .replace(/<\/th>\s*<th[^>]*>/gi, " | ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\r/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// Temporary debug endpoint — confirms outbound IP
app.get("/api/myip", async (req, res) => {
  try {
    const ip = await new Promise((resolve, reject) => {
      const r = https.get("https://ifconfig.me/ip", { headers: { "User-Agent": "curl/7.0" } }, (resp) => {
        let d = ""; resp.on("data", c => d += c); resp.on("end", () => resolve(d.trim()));
      });
      r.on("error", reject);
    });
    res.json({ outbound_ip: ip });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Search Confluence for relevant pages using CQL with fallbacks
async function searchConfluence(query) {
  const auth = Buffer.from(`${CONFLUENCE_EMAIL}:${CONFLUENCE_API_TOKEN}`).toString("base64");
  const safeQuery = query.replace(/"/g, "").trim();
  const keywords = safeQuery
    .split(/\s+/)
    .map((w) => w.trim())
    .filter((w) => w.length >= 3)
    .slice(0, 6);

  const attempts = [
    `space = "${CONFLUENCE_SPACE}" AND (title ~ "${safeQuery}" OR text ~ "${safeQuery}") ORDER BY lastmodified DESC`,
    `space = "${CONFLUENCE_SPACE}" AND title ~ "${safeQuery}" ORDER BY lastmodified DESC`,
  ];

  if (keywords.length) {
    const keywordOr = keywords.map((k) => `text ~ "${k}"`).join(" OR ");
    attempts.push(`space = "${CONFLUENCE_SPACE}" AND (${keywordOr}) ORDER BY lastmodified DESC`);
  }

  let data = { results: [] };

  for (const cql of attempts) {
    const url = `${CONFLUENCE_BASE}/rest/api/content/search?cql=${encodeURIComponent(cql)}&limit=10&expand=body.storage,title,_links`;

    data = await new Promise((resolve, reject) => {
      const req = https.get(
        url,
        { headers: { Authorization: `Basic ${auth}`, Accept: "application/json" } },
        (res) => {
          let body = "";
          res.on("data", (chunk) => (body += chunk));
          res.on("end", () => {
            if (res.statusCode !== 200) {
              reject(new Error(`Confluence search failed: ${res.statusCode} ${body.slice(0, 200)}`));
            } else {
              resolve(JSON.parse(body));
            }
          });
        }
      );
      req.on("error", reject);
      req.setTimeout(10000, () => {
        req.destroy();
        reject(new Error("Confluence request timed out"));
      });
    });

    if ((data.results || []).length > 0) {
      break;
    }
  }

  return (data.results || []).map((page) => {
    const rawHtml = page.body?.storage?.value || "";
    const text = extractConfluenceText(rawHtml)
      .slice(0, 3000); // cap per page to stay within token limits

    const pageUrl = `${CONFLUENCE_BASE}${page._links?.webui || ""}`;
    return { title: page.title, text, url: pageUrl, id: page.id };
  });
}

// Call Gemini with context from Confluence pages
async function callGemini(question, pages) {
  const contextBlock = pages.length
    ? pages
        .map((p, i) => `--- Source ${i + 1}: "${p.title}" (${p.url}) ---\n${p.text}`)
        .join("\n\n")
    : "No relevant Confluence pages were found.";

  const prompt = `You are a helpful assistant for the WNDA team at ConsoleConnect. 
You answer questions using the Confluence knowledge base content provided below.
Do NOT include source citations, URLs, or a "Source:" section in your answer — sources are displayed separately to the user.
If the context doesn't contain enough information, say so clearly.

CONFLUENCE CONTEXT:
${contextBlock}

USER QUESTION: ${question}

Answer in a clear, concise way using the context provided.`;

  const body = JSON.stringify({
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { temperature: 0.2, maxOutputTokens: 4096 },
  });

  const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;

  const response = await new Promise((resolve, reject) => {
    const options = {
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    };
    const req = https.request(geminiUrl, options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve({ status: res.statusCode, body: data }));
    });
    req.on("error", reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error("Gemini request timed out")); });
    req.write(body);
    req.end();
  });

  if (response.status !== 200) {
    const err = JSON.parse(response.body);
    throw { status: response.status, details: err };
  }

  const parsed = JSON.parse(response.body);
  const text = parsed.candidates?.[0]?.content?.parts?.[0]?.text || "";
  return text;
}

app.post("/api/chat", async (req, res) => {
  const { question } = req.body || {};
  if (!question || typeof question !== "string" || question.trim().length === 0) {
    return res.status(400).json({ error: "Missing or empty question." });
  }
  if (question.length > 1000) {
    return res.status(400).json({ error: "Question too long (max 1000 characters)." });
  }
  if (!GEMINI_API_KEY) {
    return res.status(500).json({ error: "GEMINI_API_KEY is not configured." });
  }
  if (!CONFLUENCE_API_TOKEN || !CONFLUENCE_EMAIL) {
    return res.status(500).json({ error: "Confluence credentials are not configured." });
  }

  const trimmedQuestion = question.trim();
  const smallTalkResponse = getSmallTalkResponse(trimmedQuestion);
  if (smallTalkResponse) {
    return res.json({ answer: smallTalkResponse, sources: [] });
  }

  try {
    const pages = await searchConfluence(trimmedQuestion);
    const answer = await callGemini(trimmedQuestion, pages);
    const sources = pages.map((p) => ({ title: p.title, url: p.url }));
    return res.json({ answer, sources });
  } catch (err) {
    console.error("Chat error:", JSON.stringify(err));
    if (err.status) {
      return res.status(502).json({ error: "Upstream API error.", details: err.details });
    }
    return res.status(500).json({ error: err.message || "Internal server error." });
  }
});

app.listen(PORT, () => console.log(`confluence-chat listening on port ${PORT}`));
