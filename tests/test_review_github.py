import pytest

from review.github import (
    SecretLeak,
    build_review,
    code_span,
    commentable_lines,
    find_secrets,
    risk_labels,
)
from review.reviewer import ReviewResult
from review.risk import Reason
from review.rounds import RoundPlan, parse_markers
from review.schema import Finding

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,3 +10,4 @@ def f():
     keep = 1
-    old = 2
+    new = 2
+    added = 3
     tail = 4
"""


def finding(line, severity="important", file="app.py"):
    return Finding(file=file, line=line, severity=severity, evidence="x", why="because")


def result(*findings, **kw):
    return ReviewResult(depth="standard", risk_level="medium", findings=list(findings), **kw)


def build(r, **kw):
    args = dict(head_sha="abc123", plan=RoundPlan("full", 1), risk_reasons=[], diff=DIFF)
    return build_review(r, **(args | kw))


def test_commentable_lines_are_new_side_lines_in_hunks():
    assert commentable_lines(DIFF) == {"app.py": {10, 11, 12, 13}}


def test_bot_never_approves():
    assert build(result())["event"] == "COMMENT"


def test_findings_on_changed_lines_become_inline_comments():
    payload = build(result(finding(11)))
    assert payload["comments"] == [
        {"path": "app.py", "line": 11, "side": "RIGHT", "body": "**important**: because\n\n`x`"}
    ]


def test_findings_on_unchanged_lines_go_to_the_body():
    payload = build(result(finding(99, "pre-existing")))
    assert payload["comments"] == []
    assert "app.py:99" in payload["body"]


def test_body_starts_with_marker_then_count_and_round_trips():
    payload = build(result(finding(11, "blocking")))
    marker = parse_markers([{"user": {"login": "github-actions[bot]"}, "body": payload["body"]}])
    assert marker[0].sha == "abc123" and marker[0].verdict == "block"
    assert "1 finding: 1 blocking" in payload["body"]


def test_failed_review_says_so_and_blocks():
    payload = build(result(failed=True, error="schema mismatch"))
    assert "schema mismatch" in payload["body"]
    assert "verdict=block" in payload["body"]


@pytest.mark.parametrize(
    "text",
    [
        "token sk-ant-oat01-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_secrets_are_detected(text):
    assert find_secrets(text)


def test_ordinary_code_is_not_a_secret():
    assert find_secrets("api_key: Annotated[str, Header()] = settings.api_key") == []


def test_a_secret_anywhere_in_the_payload_stops_posting():
    leaky = Finding(
        file="app.py", line=11, severity="nit",
        evidence="sk-ant-oat01-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", why="w",
    )  # fmt: skip
    with pytest.raises(SecretLeak):
        build(result(leaky))


def test_risk_labels():
    assert risk_labels("high", needs_human=False) == ["risk:high"]
    assert risk_labels("low", needs_human=True) == ["risk:low", "needs-human"]


def test_header_lookalike_lines_keep_line_numbers_in_step():
    d = "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,3 @@\n keep\n+++ x\n+after\n"
    assert commentable_lines(d) == {"app.py": {1, 2, 3}}


def test_label_removal_failure_other_than_404_is_an_error(monkeypatch):
    import subprocess as sp

    from review import github

    def fake_run(cmd, **kw):
        if "DELETE" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "HTTP 403: Resource not accessible")
        return sp.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="403"):
        github.set_labels("o/r", 1, ["risk:high"])


def test_label_removal_404_is_fine(monkeypatch):
    import subprocess as sp

    from review import github

    def fake_run(cmd, **kw):
        if "DELETE" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "HTTP 404: Label does not exist")
        return sp.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    github.set_labels("o/r", 1, ["risk:high"])


HIGH = Reason("high", "CLAUDE.md", "path", "CLAUDE.md", "steers the reviewer")
MEDIUM = Reason("medium", "app/x.py:3", "line", "text\\(", "raw SQL", "+text('a | b')")


@pytest.mark.parametrize(
    "level,needed", [("low", "none"), ("medium", "1 human"), ("high", "2 humans")]
)
def test_summary_table_shows_findings_risk_approvals_and_cost(level, needed):
    body = build(ReviewResult(depth="deep", risk_level=level, findings=[], cost_usd=0.26))["body"]
    assert "## AI review · round 1 (full) · deep" in body
    assert "| Findings | Risk | Approvals needed | Cost |" in body
    assert f"| ✅ 0 findings — nothing to fix | {level} | {needed} | $0.26 |" in body.replace(
        "🔴 ", ""
    ).replace("🟡 ", "").replace("🟢 ", "")
    assert "Risk is blast radius, not defects" in body


def test_deciding_reasons_in_a_table_the_rest_collapsed():
    r = ReviewResult(depth="deep", risk_level="high", findings=[])
    body = build(r, risk_reasons=[HIGH, MEDIUM])["body"]
    top, rest = body.split("<details>")
    assert "### Why risk is high" in top
    assert "| `CLAUDE.md` | path `CLAUDE.md` | steers the reviewer | file changed |" in top
    assert "<summary>1 more reason (medium)</summary>" in rest
    assert "| `app/x.py:3` | line `text\\(` | raw SQL | `+text('a \\| b')` |" in rest


def test_no_reasons_says_nothing_matched():
    body = build(ReviewResult(depth="quick", risk_level="low", findings=[]))["body"]
    assert "No risk floor matched, and the risk models rated it low." in body


def test_findings_table_lists_every_finding():
    body = build(result(finding(11, "blocking"), finding(99, "pre-existing")))["body"]
    assert "| Severity | Where | Why | Evidence |" in body
    assert "| blocking | `app.py:11` | because | `x` |" in body
    assert "| pre-existing | `app.py:99` | because | `x` |" in body


def test_blocking_findings_mark_the_summary():
    body = build(result(finding(11, "blocking")))["body"]
    assert "| ❌ 1 finding: 1 blocking |" in body


@pytest.mark.parametrize(
    "text,expected",
    [
        ("+q = `x`", "`` +q = `x` ``"),
        (".github/x\ny.yml", "`.github/x\\ny.yml`"),
        ("a|b", "`a\\|b`"),
        ("x" * 500, "`" + "x" * 120 + "…`"),
    ],
)
def test_code_span_cannot_be_broken_by_diff_text(text, expected):
    assert code_span(text) == expected


def test_findings_are_sorted_by_rank_with_a_legend():
    body = build(result(finding(11, "nit"), finding(12, "blocking"), finding(13, "important")))[
        "body"
    ]
    rows = [line.split(" | ")[0] for line in body.splitlines() if line.startswith("| ")]
    assert [r for r in rows if r in ("| blocking", "| important", "| nit")] == [
        "| blocking", "| important", "| nit",
    ]  # fmt: skip
    assert "**blocking**: must be fixed before merge" in body


def test_no_legend_without_findings():
    body = build(ReviewResult(depth="quick", risk_level="low", findings=[]))["body"]
    assert "must be fixed before merge" not in body


def test_inline_evidence_is_neither_truncated_nor_pipe_escaped():
    long = "a | b" + "x" * 300
    f = Finding(file="app.py", line=11, severity="important", evidence=long, why="w")
    assert build(result(f))["comments"][0]["body"].endswith(f"`{long}`")
