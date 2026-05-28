const express = require("express");

const app = express();

const PORT = process.env.PORT || 8080;
const GEMINI_API_KEY = (process.env.GEMINI_API_KEY || "").trim();
const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-2.5-flash";
const CONFLUENCE_ORIGIN = process.env.CONFLUENCE_ORIGIN || "";

app.disable("x-powered-by");
app.use(express.json({ limit: "1mb" }));
app.use(express.static("public"));

app.use((req, res, next) => {
  const frameAncestors = ["'self'"];
  if (CONFLUENCE_ORIGIN) {
    frameAncestors.push(CONFLUENCE_ORIGIN);
  }

  res.setHeader(
    "Content-Security-Policy",
    `frame-ancestors ${frameAncestors.join(" ")};`
  );
  next();
});

app.get("/healthz", (req, res) => {
  res.status(200).json({ ok: true });
});

app.post("/api/gemini", async (req, res) => {
  try {
    if (!GEMINI_API_KEY) {
      return res.status(500).json({ error: "GEMINI_API_KEY is not configured." });
    }

    const { prompt, systemInstruction } = req.body || {};
    if (!prompt || typeof prompt !== "string") {
      return res.status(400).json({ error: "prompt must be a non-empty string." });
    }

    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          systemInstruction: {
            parts: [{ text: systemInstruction || "You are a professional AI Strategy Consultant named Wanda." }],
          },
        }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      return res.status(response.status).json({
        error: "Gemini API request failed.",
        details: data,
      });
    }

    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text || "No response generated.";
    return res.status(200).json({ text });
  } catch (error) {
    return res.status(500).json({
      error: "Unexpected server error.",
      details: error.message,
    });
  }
});

app.get("*", (req, res) => {
  res.sendFile("index.html", { root: "public" });
});

app.listen(PORT, () => {
  console.log(`AI Strategy app listening on port ${PORT}`);
});
