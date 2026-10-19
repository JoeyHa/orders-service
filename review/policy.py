"""Policy the code owners declare in REVIEW.md, read from main by the CI review."""

import json
import re
from dataclasses import dataclass

from review.schema import LEVELS

FLOORS_HEADING = "## Risk floors"
_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


@dataclass(frozen=True)
class Floors:
    paths: dict[str, list[str]]  # level -> glob patterns
    content: dict[str, list[re.Pattern[str]]]  # level -> regexes over changed lines
    why: dict[str, str]  # rule (glob or regex source) -> why it raises the floor


def load_floors(review_md: str) -> Floors:
    """Parse the floors block; a missing or malformed block fails closed (raises)."""
    _, heading, rest = review_md.partition(FLOORS_HEADING)
    match = _BLOCK.search(rest) if heading else None
    if not match:
        raise ValueError(f"REVIEW.md has no '{FLOORS_HEADING}' section with a json block")
    raw = json.loads(match.group(1))

    for kind in ("paths", "content"):
        for level in raw.get(kind, {}):
            if level not in LEVELS:
                raise ValueError(f"unknown risk level '{level}' in floors.{kind}")
    content = {}
    for level, patterns in raw.get("content", {}).items():
        try:
            content[level] = [re.compile(p) for p in patterns]
        except re.error as e:
            raise ValueError(f"invalid regex in floors.content.{level}: {e}") from e
    rules = {r for kind in ("paths", "content") for rs in raw.get(kind, {}).values() for r in rs}
    why = raw.get("why", {})
    if missing := sorted(rules - why.keys()):
        raise ValueError(f"floors.why has no reason for: {missing}")
    if unknown := sorted(why.keys() - rules):
        raise ValueError(f"floors.why names rules that do not exist: {unknown}")
    if blank := sorted(r for r, v in why.items() if not isinstance(v, str) or not v.strip()):
        raise ValueError(f"floors.why is empty or not text for: {blank}")
    return Floors(paths=raw.get("paths", {}), content=content, why=why)
