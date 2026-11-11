import base64
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import markdown


PAGE_ID = "2813821015"
CONFLUENCE_URL = "https://consoleconnect.atlassian.net/wiki"
SOURCE_PATH = Path("KnowledgeBase/Data_Migration_UAT_to_Prod.md")
CODE_BLOCK_PATTERN = re.compile(
    r"<pre><code(?: class=\"language-([^\"]+)\")?>(.*?)</code></pre>",
    re.DOTALL,
)


def markdown_to_storage(source: str) -> str:
    rendered = markdown.markdown(source, extensions=["fenced_code", "tables"])

    def replace_code_block(match: re.Match[str]) -> str:
        language, encoded_code = match.groups()
        code = html.unescape(encoded_code).replace("]]>", "]]]]><![CDATA[>")
        language_parameter = ""
        if language:
            language_parameter = (
                '<ac:parameter ac:name="language">'
                f"{html.escape(language)}"
                "</ac:parameter>"
            )
        return (
            '<ac:structured-macro ac:name="code">'
            f"{language_parameter}"
            f"<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )

    return CODE_BLOCK_PATTERN.sub(replace_code_block, rendered)


def confluence_request(
    method: str, url: str, email: str, api_token: str, payload: dict | None = None
) -> dict:
    credentials = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode(
        "ascii"
    )
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(
            f"Confluence API returned HTTP {error.code}: {details}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Confluence: {error.reason}") from error


def main() -> None:
    email = os.environ.get("CONFLUENCE_EMAIL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not email or not api_token:
        raise RuntimeError(
            "Set the CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN GitHub Actions secrets."
        )
    if not SOURCE_PATH.is_file():
        raise FileNotFoundError(f"Markdown source file not found: {SOURCE_PATH}")

    storage_body = markdown_to_storage(SOURCE_PATH.read_text(encoding="utf-8"))
    page_url = f"{CONFLUENCE_URL}/api/v2/pages/{PAGE_ID}"
    page = confluence_request("GET", page_url, email, api_token)
    if page.get("id") != PAGE_ID:
        raise RuntimeError(f"Unexpected Confluence page returned for ID {PAGE_ID}.")
    if page.get("status") != "current":
        raise RuntimeError(
            f"Confluence page {PAGE_ID} is not current; refusing to update it."
        )

    version = page.get("version", {}).get("number")
    if not isinstance(version, int):
        raise RuntimeError(f"Confluence page {PAGE_ID} has no valid version number.")

    update = {
        "id": PAGE_ID,
        "status": page["status"],
        "title": page["title"],
        "spaceId": page["spaceId"],
        "body": {"representation": "storage", "value": storage_body},
        "version": {
            "number": version + 1,
            "message": "Synced from the GitHub Markdown source",
        },
    }
    if "parentId" in page:
        update["parentId"] = page["parentId"]

    result = confluence_request("PUT", page_url, email, api_token, update)
    result_version = result.get("version", {}).get("number", version + 1)
    print(f"Synced {SOURCE_PATH} to Confluence page {PAGE_ID}, version {result_version}.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
