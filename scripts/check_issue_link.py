#!/usr/bin/env python3
"""Fail a PR that has no linked, open, authorized issue (review pipeline L2).

Reads the GraphQL `pullRequest` object on stdin (see .github/workflows/issue-link.yml).
Prints GitHub annotations; exits 0 to pass, 1 to block.
"""

import json
import sys

EXEMPT_BOTS = {"dependabot[bot]", "renovate[bot]"}
BREAK_GLASS = "break-glass"
APPROVED = "approved"


def _login(node: dict) -> str | None:
    return (node.get("author") or {}).get("login")  # author is null for deleted accounts


def _labels(node: dict) -> set[str]:
    return {label["name"] for label in node["labels"]["nodes"]}


def decide(pr: dict) -> tuple[int, str]:
    author = _login(pr)
    if author in EXEMPT_BOTS:
        return 0, f"::notice::Exempt: bot author {author}; no linked issue required."
    if BREAK_GLASS in _labels(pr):
        return 0, f"::warning::{BREAK_GLASS}: issue check bypassed. Link an issue after the fact."

    issues = pr["closingIssuesReferences"]["nodes"]
    for issue in issues:
        authorized = _login(issue) != author or APPROVED in _labels(issue)
        if issue["state"] == "OPEN" and authorized:
            return 0, f"::notice::Linked issue #{issue['number']} is open and authorized."

    if not issues:
        why = 'no linked issue. Add "Closes #N" to the PR description.'
    else:
        why = (
            f"linked issues are closed, or opened by the PR author without the '{APPROVED}' label."
        )
    return 1, f"::error::Blocked: {why}"


if __name__ == "__main__":
    code, message = decide(json.load(sys.stdin))
    print(message)
    sys.exit(code)
