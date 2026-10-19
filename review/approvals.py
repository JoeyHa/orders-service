"""L6: required human approvals by risk. Bots never count; a maintainer's break-glass is logged.

Reads the GraphQL `pullRequest` object on stdin (see .github/workflows/approvals.yml).
"""

import json
import sys
from pathlib import Path

REQUIRED = {"risk:low": 0, "risk:medium": 1, "risk:high": 2}


def _applied_by(pr: dict, label: str) -> str | None:
    events = [e for e in pr["timelineItems"]["nodes"] if e["label"]["name"] == label]
    return ((events[-1]["actor"] or {}).get("login")) if events else None


def decide_approvals(pr: dict, *, maintainers: frozenset[str]) -> tuple[int, str]:
    labels = {n["name"] for n in pr["labels"]["nodes"]}
    author = (pr["author"] or {}).get("login")

    breaker = _applied_by(pr, "break-glass") if "break-glass" in labels else None
    if breaker in maintainers:
        return 0, f"::warning::break-glass applied by {breaker}: approval requirement bypassed."

    # if a stale label survived, the higher one wins: a failure must never lower the bar
    risk = max((label for label in REQUIRED if label in labels), key=REQUIRED.get, default=None)
    if risk is None:
        return 1, "::error::Blocked: PR not rated yet; waiting for the AI review to set risk."
    needed = max(REQUIRED[risk], 1 if "needs-human" in labels else 0)

    approvers = {
        r["author"]["login"]
        for r in pr["latestOpinionatedReviews"]["nodes"]
        if r["state"] == "APPROVED"
        and r["author"]["__typename"] != "Bot"
        and r["author"]["login"] != author
        and r["commit"]["oid"] == pr["headRefOid"]  # approval of the latest push only
    }
    if len(approvers) >= needed:
        return 0, f"::notice::{risk}: {len(approvers)}/{needed} human approvals."
    return 1, f"::error::Blocked: {risk} needs {needed} human approvals, has {len(approvers)}."


if __name__ == "__main__":
    path = Path(".github/maintainers.txt")
    lines = path.read_text().splitlines() if path.is_file() else []
    maintainers = frozenset(s.strip() for s in lines if s.strip() and not s.startswith("#"))
    code, message = decide_approvals(json.load(sys.stdin), maintainers=maintainers)
    print(message)
    sys.exit(code)
