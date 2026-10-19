import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from review.__main__ import run_review
from review.github import format_marker
from review.reviewer import ReviewResult
from review.risk import RiskDecision
from review.rounds import BOT_LOGIN, Marker
from review.schema import Finding

POLICY = {"review_md": "## Risk floors\n\n```json\n{}\n```\n", "claude_md": "c"}


@dataclass
class FakeIo:
    reviews: list = field(default_factory=list)
    posted: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    env_during_agents: dict = field(default_factory=dict)
    root: Path = Path(".")

    def get_reviews(self):
        return self.reviews

    def pr_text(self):
        return "title"

    def issue_text(self):
        return "issue"

    def full_diff(self):
        return "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+x\n"

    def incremental_diff(self, base):
        return f"incremental from {base}"

    def is_ancestor(self, a, b):
        return True

    def post(self, payload):
        self.posted.append(payload)

    def set_labels(self, labels):
        self.labels = labels


def bot_review(sha, round_, verdict, human=False):
    return {
        "user": {"login": BOT_LOGIN},
        "body": format_marker(Marker(sha, round_, verdict, "low", human)),
    }


def fakes(io, findings=(), seen=None):
    async def risk(diff, floors, *, pr_text, root):
        io.env_during_agents["risk"] = os.environ.get("GH_TOKEN")
        return RiskDecision(level="low")

    async def review(diff, **kw):
        io.env_during_agents["review"] = os.environ.get("GH_TOKEN")
        if seen is not None:
            seen["diff"] = diff
        return ReviewResult(depth="quick", risk_level=kw["risk_level"], findings=list(findings))

    return risk, review


def run(io, findings=(), seen=None, monkeypatch=None):
    risk, review = fakes(io, findings, seen)
    return asyncio.run(run_review(io, head_sha="head", policy=POLICY, decide=risk, review=review))


def f(sev):
    return Finding(file="x.py", line=1, severity=sev, evidence="x", why="w")


def test_clean_review_posts_and_passes(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    io = FakeIo()
    assert run(io) == 0
    assert len(io.posted) == 1 and io.labels == ["risk:low"]


def test_blocking_finding_fails_the_check():
    io = FakeIo()
    assert run(io, findings=[f("blocking")]) == 1


def test_github_token_is_absent_while_agents_run_and_restored_after(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    io = FakeIo()
    run(io)
    assert io.env_during_agents == {"risk": None, "review": None}
    assert os.environ["GH_TOKEN"] == "gh-secret"


def test_same_sha_reuses_verdict_without_posting():
    io = FakeIo(reviews=[bot_review("head", 1, "block")])
    assert run(io) == 1
    assert io.posted == []


def test_second_round_reviews_only_the_new_diff():
    io, seen = FakeIo(reviews=[bot_review("old", 1, "pass")]), {}
    run(io, seen=seen)
    assert seen["diff"] == "incremental from old"


def test_cap_hands_to_a_human_without_reviewing():
    io = FakeIo(reviews=[bot_review(f"s{i}", i + 1, "pass") for i in range(3)])
    assert run(io) == 0
    assert io.posted == [] and "needs-human" in io.labels


def test_secret_in_output_posts_nothing_and_fails():
    io = FakeIo()
    leak = Finding(file="x.py", line=1, severity="nit", why="w",
                   evidence="sk-ant-oat01-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")  # fmt: skip
    risk, _ = fakes(io)

    async def review(diff, **kw):
        return ReviewResult(depth="quick", risk_level="low", findings=[leak])

    code = asyncio.run(run_review(io, head_sha="head", policy=POLICY, decide=risk, review=review))
    assert code == 1 and io.posted == []


def test_reuse_reapplies_the_stored_risk_label():
    io = FakeIo(reviews=[bot_review("head", 1, "pass")])
    run(io)
    assert io.labels == ["risk:low"]


def test_get_reviews_flattens_every_page(monkeypatch):
    from review.__main__ import GhIo

    gh = GhIo("o/r", 1, Path("."))
    monkeypatch.setattr(gh, "_out", lambda *cmd: '[[{"id": 1}], [{"id": 2}]]')
    assert gh.get_reviews() == [{"id": 1}, {"id": 2}]


def test_subprocess_output_keeps_carriage_returns():
    # text mode would turn "\r" into "\n" and split one diff line into two, hiding content
    import sys

    from review.__main__ import GhIo

    raw = b"+x = 1\rALTER TABLE orders\n"
    out = GhIo("o/r", 1, Path("."))._out(
        sys.executable, "-c", f"import sys; sys.stdout.buffer.write({raw!r})"
    )
    assert out == raw.decode()


def test_important_finding_requests_a_human_through_the_label():
    io = FakeIo()
    assert run(io, findings=[f("important")]) == 0
    assert io.labels == ["risk:low", "needs-human"]


def test_nit_alone_requests_no_human():
    io = FakeIo()
    run(io, findings=[f("nit")])
    assert io.labels == ["risk:low"]


def test_reuse_keeps_the_human_requirement_when_the_label_write_failed():
    # round 1 posted a review needing a human, then the label call failed; the re-run reuses it
    io = FakeIo(reviews=[bot_review("head", 1, "pass", human=True)])
    run(io)
    assert io.labels == ["risk:low", "needs-human"]
