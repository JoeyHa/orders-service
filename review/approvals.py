"""L6: required human approvals by risk. Bots never count; a maintainer's break-glass is logged.

Run by .github/workflows/approvals.yml on review events, and by ai-review.yml after it sets the
risk labels (labels added with GITHUB_TOKEN do not trigger workflows).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REQUIRED = {"risk:low": 0, "risk:medium": 1, "risk:high": 2}

_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      author { login } headRefOid
      labels(first: 50) { nodes { name } }
      timelineItems(itemTypes: [LABELED_EVENT], last: 100) {
        nodes { ... on LabeledEvent { label { name } actor { login } } }
      }
      latestOpinionatedReviews(first: 50) {
        nodes { state author { login __typename } commit { oid } }
      }
    }
  }
}"""


def fetch_pr(repo: str, number: int) -> dict:
    owner, name = repo.split("/")
    cmd = ["gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"repo={name}",
           "-F", f"number={number}", "-f", f"query={_QUERY}"]  # fmt: skip
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)["data"]["repository"]["pullRequest"]


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
    pr = fetch_pr(os.environ["GITHUB_REPOSITORY"], int(os.environ["PR_NUMBER"]))
    code, message = decide_approvals(pr, maintainers=maintainers)
    print(message)
    sys.exit(code)
