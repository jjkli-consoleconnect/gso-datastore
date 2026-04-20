const { execSync } = require("child_process");

async function main() {
  const token = execSync(
    "gcloud secrets versions access latest --secret=CONFLUENCE_API_TOKEN --project pccw-internal-virtual-agent",
    { encoding: "utf8" }
  ).trim();

  const email = "jjkli@consoleconnect.com";
  const auth = Buffer.from(`${email}:${token}`).toString("base64");

  const cql = 'space = "WNDA" AND title ~ "data landscape" ORDER BY lastmodified DESC';
  const url = `https://consoleconnect.atlassian.net/wiki/rest/api/content/search?cql=${encodeURIComponent(cql)}&limit=5&expand=body.storage,title,_links`;

  const response = await fetch(url, {
    headers: {
      Authorization: `Basic ${auth}`,
      Accept: "application/json",
    },
  });

  const payload = await response.json();
  console.log("STATUS", response.status);

  for (const result of payload.results || []) {
    const body = result.body?.storage?.value || "";
    const cleaned = body
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
      .replace(/\s{2,}/g, " ")
      .trim()
      .slice(0, 1000);
    console.log(`ID=${result.id} TITLE=${result.title} LEN=${body.length}`);
    console.log(body.slice(0, 1000).replace(/\s+/g, " "));
    console.log("CLEANED:");
    console.log(cleaned);
    console.log("---");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});