"""Contracts between the review agents and our code (one source: JSON Schema + validation)."""

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["low", "medium", "high"]
Severity = Literal["blocking", "important", "nit", "pre-existing"]
LEVELS: tuple[Level, ...] = ("low", "medium", "high")


def max_level(*levels: Level) -> Level:
    return max(levels, key=LEVELS.index)


class Finding(BaseModel):
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    severity: Severity
    evidence: str = Field(min_length=1, description="Code quoted from file:line that proves it")
    why: str = Field(min_length=1, description="What breaks, for whom, and when")


class Review(BaseModel):
    summary: str = Field(description="Starts with the count, e.g. '2 findings (1 blocking)'")
    findings: list[Finding]


class RiskVerdict(BaseModel):
    level: Level
    reasons: list[str]
    evidence: list[str] = Field(
        default_factory=list, description="file:line citations; required to rate above low"
    )
