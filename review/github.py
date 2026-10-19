"""Turn a review into GitHub API payloads, and send them.

The bot only ever COMMENTs (never approves). Nothing is sent if the payload contains
anything that looks like a secret.
"""

import json
import re
import subprocess

from review.reviewer import ReviewResult, summarize
from review.rounds import Marker, RoundPlan, format_marker

_SECRETS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
RISK_LABELS = ("risk:low", "risk:medium", "risk:high")


class SecretLeak(RuntimeError):
    """The review payload contains something that looks like a credential."""


def find_secrets(text: str) -> list[str]:
    return [m.group(0) for pattern in _SECRETS for m in pattern.finditer(text)]


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """New-side line numbers GitHub accepts inline comments on (added or context lines)."""
    lines: dict[str, set[int]] = {}
    path, n = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            path = None if name == "/dev/null" else name.removeprefix("b/")
        elif line.startswith("--- ") or line.startswith("diff "):
            continue
        elif match := _HUNK.match(line):
            n = int(match.group(1))
        elif path and line[:1] in (" ", "+"):
            lines.setdefault(path, set()).add(n)
            n += 1
    return lines


def build_review(
    result: ReviewResult, *, head_sha: str, plan: RoundPlan, risk_reasons: list[str], diff: str
) -> dict:
    marker = Marker(head_sha, plan.round, "block" if result.blocking else "pass", result.risk_level)
    on_diff = commentable_lines(diff)
    inline, elsewhere = [], []
    for f in result.findings:
        if f.line in on_diff.get(f.file, set()):
            body = f"**{f.severity}**: {f.why}\n\n`{f.evidence}`"
            inline.append({"path": f.file, "line": f.line, "side": "RIGHT", "body": body})
        else:
            elsewhere.append(f"- `{f.file}:{f.line}` **{f.severity}**: {f.why}")

    parts = [
        format_marker(marker),
        f"### AI review: round {plan.round} ({plan.action}), {result.depth} depth",
    ]
    if result.failed:
        parts.append(f"**Review failed, so this check blocks:** {result.error}")
    else:
        parts.append(f"**{summarize(result.findings, len(result.unverified))}**")
    parts.append(f"**Risk: {result.risk_level}**")
    parts += [f"- {r}" for r in risk_reasons]
    if result.escalated:
        parts.append("A quick review found a blocking issue, so it was re-reviewed at deep depth.")
    if elsewhere:
        parts += ["Findings outside the changed lines:", *elsewhere]
    if result.dropped_nits:
        parts.append(f"{result.dropped_nits} more nits not shown (cap is 3).")
    parts.append(f"Cost: ${result.cost_usd:.2f}")

    payload = {"commit_id": head_sha, "event": "COMMENT", "body": "\n\n".join(parts)}
    payload["comments"] = inline
    if find_secrets(json.dumps(payload)):
        raise SecretLeak("review output contains a credential-like string; nothing was posted")
    return payload


def risk_labels(level: str, *, needs_human: bool) -> list[str]:
    return [f"risk:{level}"] + (["needs-human"] if needs_human else [])


def _gh(*args: str, payload: dict | None = None) -> str:
    out = subprocess.run(
        ["gh", "api", *args], input=json.dumps(payload) if payload else None,
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout


def post_review(repo: str, pr: int, payload: dict) -> None:
    _gh("--method", "POST", f"repos/{repo}/pulls/{pr}/reviews", "--input", "-", payload=payload)


def set_labels(repo: str, pr: int, labels: list[str]) -> None:
    for stale in set(RISK_LABELS) - set(labels):
        subprocess.run(
            ["gh", "api", "--method", "DELETE", f"repos/{repo}/issues/{pr}/labels/{stale}"],
            capture_output=True,
        )  # absent labels 404; that's fine
    _gh("--method", "POST", f"repos/{repo}/issues/{pr}/labels", "--input", "-",
        payload={"labels": labels})  # fmt: skip
