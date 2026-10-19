#!/usr/bin/env python3
"""Fail a PR that has no linked, open, authorized issue (review pipeline L2).

Reads the GraphQL `pullRequest` object on stdin (see .github/workflows/issue-link.yml).
Prints GitHub annotations; exits 0 to pass, 1 to block.

Authorized: the issue was opened by someone other than the PR author, or someone other than
the PR author applied the `approved` label. `break-glass` counts only when a maintainer
(listed in MAINTAINERS_FILE, read from main) applied it. Unknown actors never count.
"""

import json
import os
import sys
from pathlib import Path

EXEMPT_BOTS = {"dependabot[bot]", "renovate[bot]"}
BREAK_GLASS = "break-glass"
APPROVED = "approved"


def _login(node: dict | None) -> str | None:
    return (node or {}).get("login")  # null for deleted accounts


def _labels(node: dict) -> set[str]:
    return {label["name"] for label in node["labels"]["nodes"]}


def _applied_by(node: dict, label: str) -> str | None:
    """Who applied a label that is currently on the node (latest labeled event)."""
    if label not in _labels(node):
        return None
    events = [e for e in node["timelineItems"]["nodes"] if e["label"]["name"] == label]
    return _login(events[-1]["actor"]) if events else None


def _maintainers() -> set[str]:
    path = Path(os.environ.get("MAINTAINERS_FILE", ".github/maintainers.txt"))
    if not path.is_file():
        return set()
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def decide(pr: dict) -> tuple[int, str]:
    author = _login(pr["author"])
    if author in EXEMPT_BOTS:
        return 0, f"::notice::Exempt: bot author {author}; no linked issue required."

    breaker = _applied_by(pr, BREAK_GLASS)
    if breaker and breaker in _maintainers():
        return 0, (
            f"::warning::{BREAK_GLASS} applied by {breaker}: issue check bypassed. "
            "Link an issue after the fact."
        )

    issues = pr["closingIssuesReferences"]["nodes"]
    for issue in issues:
        approver = _applied_by(issue, APPROVED)
        authorized = _login(issue["author"]) != author or (approver and approver != author)
        if issue["state"] == "OPEN" and authorized:
            return 0, f"::notice::Linked issue #{issue['number']} is open and authorized."

    if not issues:
        why = 'no linked issue. Add "Closes #N" to the PR description.'
    else:
        why = (
            "linked issues are closed, or opened by the PR author and not "
            f"'{APPROVED}' by someone else."
        )
    if BREAK_GLASS in _labels(pr):
        why += f" '{BREAK_GLASS}' ignored: not applied by a maintainer."
    return 1, f"::error::Blocked: {why}"


if __name__ == "__main__":
    code, message = decide(json.load(sys.stdin))
    print(message)
    sys.exit(code)
