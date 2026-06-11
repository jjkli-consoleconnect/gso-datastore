from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


SOURCE_MD = Path(r"g:/My Drive/Scripts/KnowledgeBase/RemedyJiraWorkLogView.md")
TARGET_MD = Path(r"g:/My Drive/Scripts/KnowledgeBase/RemedyJira.md")


def main() -> None:
    content = SOURCE_MD.read_text(encoding="utf-8")
    content = content.replace("RemedyJiraWorkLogView", "RemedyJira")
    content = content.replace("- Total fields: 198", "- Total fields: 197")
    content = content.replace(
        "| Device_Names | STRING | REPEATED | Distinct device identifiers extracted from Remedy work-log text using regex tokenization. |\n",
        "",
    )
    content = content.replace(
        "_Generated for LLM schema reference: 2026-06-01 10:12:07 UTC_",
        f"_Generated for LLM schema reference: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}_",
    )
    TARGET_MD.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()