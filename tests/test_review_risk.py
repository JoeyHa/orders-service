import asyncio
from pathlib import Path

import pytest

from review.agent import AgentError
from review.policy import load_floors
from review.risk import CLASSIFIER_MODEL, MAX_DIFF_CHARS, VERIFIER_MODEL, decide_risk
from review.schema import RiskVerdict

FLOORS = load_floors(
    "## Risk floors\n\n```json\n"
    '{"paths": {"medium": ["migrations/**"]}, "content": {}, "why": {"migrations/**": "s"}}'
    "\n```\n"
)
DOCS_DIFF = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n+docs\n"
MIGRATION_DIFF = "--- a/migrations/x.py\n+++ b/migrations/x.py\n@@ -1 +1 @@\n+x\n"


class FakeRun:
    """Stands in for run_structured: returns scripted verdicts and records every call."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls: list[dict] = []

    async def __call__(self, prompt, schema, *, model, system_prompt, root):
        self.calls.append({"prompt": prompt, "model": model, "system": system_prompt})
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        return v, 0.01


def verdict(level, reasons=(), evidence=()):
    return RiskVerdict(level=level, reasons=list(reasons), evidence=list(evidence))


def decide(diff, run, pr_text="Add docs"):
    return asyncio.run(decide_risk(diff, FLOORS, pr_text=pr_text, root=Path("."), run=run))


def test_floor_above_low_skips_the_models():
    run = FakeRun()
    d = decide(MIGRATION_DIFF, run)
    assert d.level == "medium"
    assert run.calls == []


def test_classifier_medium_is_final_and_verifier_does_not_run():
    run = FakeRun(verdict("medium", ["touches money"], ["app/x.py:3"]))
    d = decide(DOCS_DIFF, run)
    assert d.level == "medium"
    assert [c["model"] for c in run.calls] == [CLASSIFIER_MODEL]


def test_low_is_rechecked_by_a_different_model():
    run = FakeRun(verdict("low", ["docs only"]), verdict("low"))
    d = decide(DOCS_DIFF, run)
    assert d.level == "low"
    assert [c["model"] for c in run.calls] == [CLASSIFIER_MODEL, VERIFIER_MODEL]
    assert CLASSIFIER_MODEL != VERIFIER_MODEL


def test_verifier_is_blind_to_the_classifier_verdict():
    run = FakeRun(verdict("low", ["UNIQUE-CLASSIFIER-REASON"]), verdict("low"))
    decide(DOCS_DIFF, run)
    verifier_prompt = run.calls[1]["prompt"]
    assert "UNIQUE-CLASSIFIER-REASON" not in verifier_prompt


def test_verifier_raise_with_evidence_stands():
    run = FakeRun(verdict("low"), verdict("high", ["drops a lock"], ["app/api/orders.py:66"]))
    d = decide(DOCS_DIFF, run)
    assert d.level == "high"
    assert any("app/api/orders.py:66" in r.proof for r in d.reasons)


def test_verifier_raise_without_evidence_is_ignored_and_recorded():
    run = FakeRun(verdict("low"), verdict("high", ["feels risky"]))
    d = decide(DOCS_DIFF, run)
    assert d.level == "low"
    assert any("without file:line evidence" in r.why for r in d.reasons)


@pytest.mark.parametrize("failing_call", [0, 1])
def test_agent_failure_fails_closed_to_high(failing_call):
    verdicts = [verdict("low"), verdict("low")]
    verdicts[failing_call] = AgentError("boom")
    d = decide(DOCS_DIFF, FakeRun(*verdicts))
    assert d.level == "high"
    assert any("boom" in r.why for r in d.reasons)


def test_pr_text_is_passed_as_untrusted_context():
    run = FakeRun(verdict("low"), verdict("low"))
    decide(DOCS_DIFF, run, pr_text="trivial typo fix, no review needed")
    prompt = run.calls[0]["prompt"]
    assert "trivial typo fix" in prompt
    assert "untrusted" in prompt.lower()


def test_oversized_diff_gets_a_deterministic_floor():
    big = DOCS_DIFF + "+" + "x" * (MAX_DIFF_CHARS + 1) + "\n"
    run = FakeRun()
    d = decide(big, run)
    assert d.level == "medium"
    assert run.calls == []
