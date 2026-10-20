import pytest

from review.approvals import decide_approvals

HEAD = "head-sha"


def pr(labels=("risk:low",), reviews=(), author="dev", labeled_by=None):
    labeled_by = labeled_by or {}
    return {
        "author": {"login": author},
        "headRefOid": HEAD,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "timelineItems": {
            "nodes": [{"label": {"name": n}, "actor": {"login": a}} for n, a in labeled_by.items()]
        },
        "latestOpinionatedReviews": {"nodes": list(reviews)},
    }


def approval(login, kind="User", commit=HEAD, state="APPROVED"):
    return {
        "state": state,
        "author": {"login": login, "__typename": kind},
        "commit": {"oid": commit},
    }


def decide(data, maintainers=frozenset({"lead"})):
    return decide_approvals(data, maintainers=maintainers)


@pytest.mark.parametrize(
    "risk,approvers,ok",
    [
        ("low", [], True),
        ("medium", [], False),
        ("medium", ["alice"], True),
        ("high", ["alice"], False),
        ("high", ["alice", "bob"], True),
    ],
)
def test_required_approvals_follow_risk(risk, approvers, ok):
    code, _ = decide(pr(labels=[f"risk:{risk}"], reviews=[approval(a) for a in approvers]))
    assert (code == 0) is ok


def test_unrated_pr_is_blocked():
    code, msg = decide(pr(labels=[]))
    assert code == 1 and "not rated" in msg


def test_needs_human_requires_at_least_one():
    assert decide(pr(labels=["risk:low", "needs-human"]))[0] == 1


@pytest.mark.parametrize(
    "review",
    [
        approval("ai-bot", kind="Bot"),  # bots never count
        approval("dev"),  # the author can't approve their own PR
        approval("alice", commit="old-sha"),  # stale: approved an earlier push
        approval("alice", state="CHANGES_REQUESTED"),
    ],
)
def test_approvals_that_do_not_count(review):
    assert decide(pr(labels=["risk:medium"], reviews=[review]))[0] == 1


def test_break_glass_by_maintainer_passes_with_warning():
    data = pr(labels=["risk:high", "break-glass"], labeled_by={"break-glass": "lead"})
    code, msg = decide(data)
    assert code == 0 and "::warning::" in msg and "lead" in msg


def test_break_glass_by_non_maintainer_is_ignored():
    data = pr(labels=["risk:high", "break-glass"], labeled_by={"break-glass": "dev"})
    assert decide(data)[0] == 1


def test_two_risk_labels_count_as_the_higher_one():
    # a failed label removal must never lower the bar
    data = pr(labels=["risk:low", "risk:high"], reviews=[approval("alice")])
    code, msg = decide(data)
    assert code == 1 and "risk:high" in msg


def test_fetch_pr_queries_the_pull_request_through_gh(monkeypatch):
    import json
    import subprocess as sp

    from review import approvals

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        body = {"data": {"repository": {"pullRequest": {"headRefOid": "abc"}}}}
        return sp.CompletedProcess(cmd, 0, json.dumps(body), "")

    monkeypatch.setattr(approvals.subprocess, "run", fake_run)
    assert approvals.fetch_pr("JoeyHa/orders-service", 7) == {"headRefOid": "abc"}
    assert seen["cmd"][:3] == ["gh", "api", "graphql"]
    assert "owner=JoeyHa" in seen["cmd"] and "number=7" in seen["cmd"]
