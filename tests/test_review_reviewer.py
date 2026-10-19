import asyncio
from pathlib import Path

import pytest

from review.agent import AgentError
from review.reviewer import DEPTHS, review_pr, summarize, verify_findings
from review.schema import Finding, Review


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("a = 1\nb = 2\nstmt = select(Order)\nreturn stmt\n")
    return tmp_path


def f(severity="important", line=3, evidence="stmt = select(Order)", file="app.py"):
    return Finding(file=file, line=line, severity=severity, evidence=evidence, why="w")


class FakeRun:
    def __init__(self, *reviews):
        self.reviews = list(reviews)
        self.models: list[str] = []
        self.prompts: list[str] = []

    async def __call__(self, prompt, schema, *, model, system_prompt, root):
        self.models.append(model)
        self.prompts.append(system_prompt + "\n" + prompt)
        r = self.reviews.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, 0.02


def review(run, root, risk="low", **kw):
    return asyncio.run(
        review_pr(
            "diff", pr_text="t", issue_text="i", risk_level=risk,
            review_md="RULES", claude_md="CONVENTIONS", root=root, run=run, **kw,
        )
    )  # fmt: skip


def test_evidence_must_appear_near_the_cited_line(root):
    ok, bad = verify_findings(
        [f(), f(line=1), f(evidence="not in file"), f(file="missing.py"), f(file="../x")], root
    )
    assert ok == [f(), f(line=1)]  # line 1 is within the window around line 3
    assert len(bad) == 3


def test_summary_count_is_computed_not_trusted(root):
    s = summarize([f("blocking"), f("nit"), f("pre-existing")], unverified=1)
    assert s.startswith("3 findings: 1 blocking · 1 nit · 1 pre-existing")
    assert summarize([f("important")], unverified=0) == "1 finding: 1 important"
    assert "1 unverified finding not posted" in s
    assert summarize([], unverified=0) == "0 findings — nothing to fix."


@pytest.mark.parametrize("risk,depth", [("low", "quick"), ("medium", "standard"), ("high", "deep")])
def test_depth_follows_risk(root, risk, depth):
    run = FakeRun(Review(summary="x", findings=[]))
    r = review(run, root, risk=risk)
    assert r.depth == depth
    assert run.models == [DEPTHS[depth]]


def test_quick_review_with_blocking_finding_escalates_to_deep(root):
    run = FakeRun(Review(summary="", findings=[f("blocking")]), Review(summary="", findings=[]))
    r = review(run, root, risk="low")
    assert run.models == [DEPTHS["quick"], DEPTHS["deep"]]
    assert r.depth == "deep" and r.escalated and r.risk_level == "high"
    assert r.findings == []  # the deep review's findings replace the quick ones


def test_nits_are_capped_at_three(root):
    run = FakeRun(Review(summary="", findings=[f("nit")] * 5 + [f("important")]))
    r = review(run, root, risk="medium")
    assert [x.severity for x in r.findings].count("nit") == 3
    assert r.dropped_nits == 2


def test_policy_and_issue_reach_the_prompt(root):
    run = FakeRun(Review(summary="", findings=[]))
    review(run, root)
    assert "RULES" in run.prompts[0] and "CONVENTIONS" in run.prompts[0]
    assert "untrusted" in run.prompts[0].lower()


def test_agent_failure_fails_the_review(root):
    r = review(FakeRun(AgentError("schema")), root, risk="medium")
    assert r.failed and "schema" in r.error
    assert r.blocking  # a reviewer that could not run must not pass the check


def test_blocking_property(root):
    run = FakeRun(Review(summary="", findings=[f("important"), f("pre-existing")]))
    assert not review(run, root, risk="medium").blocking


def test_every_rank_has_one_meaning_shared_by_prompt_and_report():
    from typing import get_args

    from review.reviewer import SEVERITIES, SYSTEM
    from review.schema import SEVERITY_MEANING, Severity

    assert tuple(SEVERITY_MEANING) == get_args(Severity)  # rank order, most severe first
    assert "Severity: {severities}." in SYSTEM
    assert all(f"{s} = {m}" in SEVERITIES for s, m in SEVERITY_MEANING.items())


def test_summary_when_every_finding_is_unverified(root):
    assert summarize([], unverified=1) == (
        "0 findings; 1 unverified finding not posted (evidence not found in file)"
    )
