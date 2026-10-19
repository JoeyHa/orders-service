import pytest

from review.github import (
    SecretLeak,
    build_review,
    commentable_lines,
    find_secrets,
    risk_labels,
)
from review.reviewer import ReviewResult
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
    args = dict(head_sha="abc123", plan=RoundPlan("full", 1), risk_reasons=["r1"], diff=DIFF)
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
    assert "1 findings (1 blocking)" in payload["body"]


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
