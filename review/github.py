"""Turn a review into GitHub API payloads, and send them.

The bot only ever COMMENTs (never approves). Nothing is sent if the payload contains
anything that looks like a secret.
"""

import json
import re
import subprocess

from review.approvals import REQUIRED
from review.diff import parse_diff
from review.reviewer import ReviewResult, summarize
from review.risk import Reason
from review.rounds import Marker, RoundPlan, format_marker

_SECRETS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
RISK_LABELS = ("risk:low", "risk:medium", "risk:high")
MAX_CODE_CHARS = 120
_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}
_HUMANS = {0: "none", 1: "1 human"}


class SecretLeak(RuntimeError):
    """The review payload contains something that looks like a credential."""


def find_secrets(text: str) -> list[str]:
    return [m.group(0) for pattern in _SECRETS for m in pattern.finditer(text)]


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """New-side line numbers GitHub accepts inline comments on (added or context lines)."""
    lines: dict[str, set[int]] = {}
    for line in parse_diff(diff)[1]:
        if line.new_line is not None:
            lines.setdefault(line.path, set()).add(line.new_line)
    return lines


def code_span(text: str) -> str:
    """Code span safe inside a table cell; diff text is author-controlled and must not escape."""
    text = text.replace("\r", "\\r").replace("\n", "\\n")  # a line break ends the span
    if len(text) > MAX_CODE_CHARS:
        text = text[:MAX_CODE_CHARS] + "…"
    text = text.replace("|", "\\|")  # GitHub splits table cells on | even inside code
    if "`" not in text:
        return f"`{text}`"
    fence = "`" * (max(len(run) for run in re.findall(r"`+", text)) + 1)
    return f"{fence} {text} {fence}"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _table(header: str, rows: list[str]) -> str:
    cols = header.count("|") - 1
    return "\n".join([header, "|" + "---|" * cols, *rows])


def _reason_row(r: Reason) -> str:
    where = code_span(r.where) if r.where else "whole PR"
    rule = f"{r.kind} {code_span(r.rule)}" if r.rule else r.kind
    proof = code_span(r.proof) if r.proof else ("file changed" if r.kind == "path" else "—")
    return f"| {where} | {rule} | {_cell(r.why)} | {proof} |"


def _risk_section(level: str, reasons: list[Reason]) -> list[str]:
    head = f"### Why risk is {level}"
    if not reasons:
        if level == "low":
            return [head, "No risk floor matched, and the risk models rated it low."]
        return [head, "Raised by the code review itself (see findings)."]
    header = "| Where | Rule | Why | Proof |"
    top = [r for r in reasons if r.level == level] or reasons
    rest = [r for r in reasons if r not in top]
    parts = [head, _table(header, [_reason_row(r) for r in top])]
    if rest:
        n = len(rest)
        levels = ", ".join(dict.fromkeys(r.level for r in rest))
        summary = f"{n} more reason{'s' if n > 1 else ''} ({levels})"
        rows = _table(header, [_reason_row(r) for r in rest])
        parts.append(f"<details><summary>{summary}</summary>\n\n{rows}\n\n</details>")
    return parts


def build_review(
    result: ReviewResult, *, head_sha: str, plan: RoundPlan, risk_reasons: list[Reason], diff: str
) -> dict:
    marker = Marker(head_sha, plan.round, "block" if result.blocking else "pass", result.risk_level)
    on_diff = commentable_lines(diff)
    inline = [
        {"path": f.file, "line": f.line, "side": "RIGHT",
         "body": f"**{f.severity}**: {f.why}\n\n{code_span(f.evidence)}"}
        for f in result.findings if f.line in on_diff.get(f.file, set())
    ]  # fmt: skip

    if result.failed:
        verdict = "❌ review failed"
    else:
        icon = "❌" if result.blocking else ("⚠️" if result.findings else "✅")
        verdict = f"{icon} {summarize(result.findings, len(result.unverified)).rstrip('.')}"
    needed = REQUIRED[f"risk:{result.risk_level}"]
    humans = _HUMANS.get(needed, f"{needed} humans")
    risk = f"{_ICON[result.risk_level]} {result.risk_level}"

    parts = [
        format_marker(marker),
        f"## AI review · round {plan.round} ({plan.action}) · {result.depth}",
        _table("| Findings | Risk | Approvals needed | Cost |",
               [f"| {_cell(verdict)} | {risk} | {humans} | ${result.cost_usd:.2f} |"]),
        "> Risk is blast radius, not defects: it sets how many humans must approve, "
        "even when there is nothing to fix.",
    ]  # fmt: skip
    if result.failed:
        parts.append(f"**The review failed, so this check blocks:** {_cell(result.error)}")
    parts += _risk_section(result.risk_level, risk_reasons)
    parts.append("### Findings")
    if result.findings:
        rows = [
            f"| {f.severity} | {code_span(f'{f.file}:{f.line}')} | {_cell(f.why)} "
            f"| {code_span(f.evidence)} |"
            for f in result.findings
        ]
        parts.append(_table("| Severity | Where | Why | Evidence |", rows))
    else:
        parts.append("None.")
    if result.escalated:
        parts.append("A quick review found a blocking issue, so it was re-reviewed at deep depth.")
    if result.dropped_nits:
        parts.append(f"{result.dropped_nits} more nits not shown (cap is 3).")

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
        out = subprocess.run(
            ["gh", "api", "--method", "DELETE", f"repos/{repo}/issues/{pr}/labels/{stale}"],
            capture_output=True, text=True,
        )  # fmt: skip
        if out.returncode != 0 and "404" not in out.stderr:  # absent label: fine
            raise RuntimeError(f"could not remove {stale}: {out.stderr.strip()}")
    _gh("--method", "POST", f"repos/{repo}/issues/{pr}/labels", "--input", "-",
        payload={"labels": labels})  # fmt: skip
