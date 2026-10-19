import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_issue_link.py"


def labels(*names: str) -> dict:
    return {"nodes": [{"name": n} for n in names]}


def issue(number=1, state="OPEN", author="alice", *issue_labels: str) -> dict:
    return {
        "number": number,
        "state": state,
        "author": {"login": author},
        "labels": labels(*issue_labels),
    }


def pr(author="bob", issues=(), pr_labels=()) -> dict:
    return {
        "author": {"login": author},
        "labels": labels(*pr_labels),
        "closingIssuesReferences": {"nodes": list(issues)},
    }


def run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT], input=json.dumps(payload), text=True, capture_output=True
    )


def test_blocks_without_linked_issue():
    r = run(pr())
    assert r.returncode == 1
    assert "::error::" in r.stdout


def test_passes_with_open_issue_from_someone_else():
    assert run(pr(issues=[issue(author="alice")])).returncode == 0


def test_blocks_when_only_closed_issues_are_linked():
    assert run(pr(issues=[issue(state="CLOSED")])).returncode == 1


def test_blocks_self_authored_issue_without_approval():
    assert run(pr(author="bob", issues=[issue(author="bob")])).returncode == 1


def test_passes_self_authored_issue_with_approved_label():
    assert run(pr(author="bob", issues=[issue(1, "OPEN", "bob", "approved")])).returncode == 0


def test_passes_if_any_linked_issue_qualifies():
    issues = [issue(1, "CLOSED"), issue(2, "OPEN", "bob"), issue(3, "OPEN", "alice")]
    assert run(pr(author="bob", issues=issues)).returncode == 0


@pytest.mark.parametrize("bot", ["dependabot[bot]", "renovate[bot]"])
def test_bots_are_exempt_and_logged(bot):
    r = run(pr(author=bot))
    assert r.returncode == 0
    assert "::notice::" in r.stdout


def test_break_glass_is_exempt_and_logged():
    r = run(pr(pr_labels=["break-glass"]))
    assert r.returncode == 0
    assert "::warning::" in r.stdout and "break-glass" in r.stdout


def test_ghost_author_is_handled():
    # deleted GitHub accounts come back as author: null
    payload = pr(issues=[issue()])
    payload["closingIssuesReferences"]["nodes"][0]["author"] = None
    assert run(payload).returncode == 0
