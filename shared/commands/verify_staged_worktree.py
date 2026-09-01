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
    unstaged_files = set(git_output("diff", "--name-only"))
    partially_staged_python = [
        path for path in staged_files if path.endswith(".py") and path in unstaged_files
    ]

    if not missing_files and not partially_staged_python:
        return 0

    print("Formatting hooks cannot safely update the staged Python snapshot.")
    if missing_files:
        print("Staged files missing locally:")
        print(*missing_files, sep="\n")
    if partially_staged_python:
        print("Python files with both staged and unstaged changes:")
        print(*partially_staged_python, sep="\n")
    print(
        "Stage the intended versions with `git add <file>`, then commit again."
        " Use `git restore --staged <file>` instead for entries that should not be committed."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
