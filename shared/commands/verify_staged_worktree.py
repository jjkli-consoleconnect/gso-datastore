"""Prevent auto-fixing hooks from conflicting with unstaged file changes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def git_output(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    staged_files = git_output("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    missing_files = [path for path in staged_files if not Path(path).is_file()]

    if not missing_files:
        return 0

    print(
        "Staged files are missing from the working tree; formatting hooks cannot safely apply fixes."
    )
    print("Missing locally:")
    print(*missing_files, sep="\n")
    print(
        "Stage the intended versions with `git add <file>` or remove stale entries with `git restore --staged <file>`."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
