"""Validate commit messages against the Forge convention.

Format: ``[scope/op]: title`` with an imperative title, subject line under 72
characters. Merge commits are exempt. Used by the pre-commit ``commit-msg``
hook (``--message-file``) and by CI over a revision range (``--range``).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SUBJECT_PATTERN = re.compile(
    r"^\[[a-z0-9-]+/(feat|fix|refactor|test|docs|chore|perf|style|ci|build|revert)\]!?: \S.*$"
)
MAX_SUBJECT_LENGTH = 72
EXEMPT_PREFIXES = ("Merge ",)


def check_subject(subject: str) -> list[str]:
    """Return a list of problems for one commit subject line."""
    if subject.startswith(EXEMPT_PREFIXES):
        return []
    problems: list[str] = []
    if not SUBJECT_PATTERN.match(subject):
        problems.append(
            "subject must match '[scope/op]: title' with op in "
            "feat|fix|refactor|test|docs|chore|perf|style|ci|build|revert"
        )
    if len(subject) > MAX_SUBJECT_LENGTH:
        problems.append(f"subject exceeds {MAX_SUBJECT_LENGTH} characters ({len(subject)})")
    return problems


def check_message_file(path: str) -> int:
    """Validate the message being written by ``git commit``."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    subject = next(
        (line for line in lines if line.strip() and not line.startswith("#")),
        "",
    )
    problems = check_subject(subject)
    if problems:
        print(f"commit message rejected: {subject!r}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    return 0


def check_range(rev_range: str) -> int:
    """Validate every commit subject in a revision range."""
    completed = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x09%s", rev_range],
        capture_output=True,
        text=True,
        check=True,
    )
    failures = 0
    for line in completed.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        problems = check_subject(subject)
        if problems:
            failures += 1
            print(f"{sha[:10]} rejected: {subject!r}")
            for problem in problems:
                print(f"  - {problem}")
    if failures:
        print(f"{failures} commit(s) violate the Forge convention; see CONTRIBUTING.md")
        return 1
    print("all commit messages follow the Forge convention")
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message-file", help="path to the commit message file")
    group.add_argument("--range", dest="rev_range", help="git revision range to validate")
    args = parser.parse_args()
    if args.message_file:
        return check_message_file(args.message_file)
    return check_range(args.rev_range)


if __name__ == "__main__":
    sys.exit(main())
