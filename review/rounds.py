"""Review rounds: one verdict per commit, incremental after round 1, capped.

State lives in hidden markers in the bot's own PR comments; markers from anyone else are
ignored, so a PR author cannot forge a passing verdict.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

BOT_LOGIN = "github-actions[bot]"
MAX_ROUNDS = 3
_MARKER = re.compile(
    r"<!-- ai-review sha=(\w+) round=(\d+) verdict=(pass|block) risk=(low|medium|high) -->"
)


@dataclass(frozen=True)
class Marker:
    sha: str
    round: int
    verdict: Literal["pass", "block"]
    risk: Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RoundPlan:
    action: Literal["reuse", "full", "incremental", "cap"]
    round: int
    base: str | None = None
    prior: Marker | None = None


def format_marker(m: Marker) -> str:
    return f"<!-- ai-review sha={m.sha} round={m.round} verdict={m.verdict} risk={m.risk} -->"


def parse_markers(comments: list[dict]) -> list[Marker]:
    markers = []
    for c in comments:
        if (c.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        if match := _MARKER.search(c.get("body") or ""):
            sha, round_, verdict, risk = match.groups()
            markers.append(Marker(sha, int(round_), verdict, risk))
    return markers


def plan_round(
    markers: list[Marker], head_sha: str, *, is_ancestor: Callable[[str, str], bool]
) -> RoundPlan:
    for m in markers:
        if m.sha == head_sha:
            return RoundPlan("reuse", m.round, prior=m)
    if not markers:
        return RoundPlan("full", 1)
    last = markers[-1]
    if len(markers) >= MAX_ROUNDS:
        return RoundPlan("cap", len(markers), prior=last)
    if is_ancestor(last.sha, head_sha):
        return RoundPlan("incremental", len(markers) + 1, base=last.sha, prior=last)
    return RoundPlan("full", len(markers) + 1, prior=last)  # rebase / force-push
