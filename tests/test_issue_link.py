import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_issue_link.py"


def labeled(names_and_actors: dict[str, str | None]) -> dict:
    """Current labels plus the timeline events that applied them."""
    return {
        "labels": {"nodes": [{"name": n} for n in names_and_actors]},
        "timelineItems": {
            "nodes": [
                {"label": {"name": n}, "actor": None if a is None else {"login": a}}
                for n, a in names_and_actors.items()
            ]
        },
    }


def issue(number=1, state="OPEN", author="alice", approved_by: str | None = "") -> dict:
    node = {"number": number, "state": state, "author": {"login": author}}
    return node | labeled({} if approved_by == "" else {"approved": approved_by})


def pr(author="bob", issues=(), break_glass_by: str | None = "") -> dict:
    node = {"author": {"login": author}, "closingIssuesReferences": {"nodes": list(issues)}}
    return node | labeled({} if break_glass_by == "" else {"break-glass": break_glass_by})


@pytest.fixture
def maintainers(tmp_path: Path) -> Path:
    f = tmp_path / "maintainers.txt"
    f.write_text("# one GitHub login per line\ncarol\nbob\n")
    return f


def run(payload: dict, maintainers_file: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "MAINTAINERS_FILE": str(maintainers_file or "/nonexistent")}
    return subprocess.run(
        [sys.executable, SCRIPT], input=json.dumps(payload), text=True, capture_output=True, env=env
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


def test_blocks_self_authored_issue_self_approved():
    assert run(pr(author="bob", issues=[issue(author="bob", approved_by="bob")])).returncode == 1


def test_passes_self_authored_issue_approved_by_someone_else():
    r = run(pr(author="bob", issues=[issue(author="bob", approved_by="alice")]))
    assert r.returncode == 0


def test_blocks_approval_with_unknown_actor():
    # deleted accounts come back as actor: null; unknown is not "someone else"
    assert run(pr(author="bob", issues=[issue(author="bob", approved_by=None)])).returncode == 1


def test_passes_if_any_linked_issue_qualifies():
    issues = [issue(1, "CLOSED"), issue(2, "OPEN", "bob"), issue(3, "OPEN", "alice")]
    assert run(pr(author="bob", issues=issues)).returncode == 0


@pytest.mark.parametrize("bot", ["dependabot[bot]", "renovate[bot]"])
def test_bots_are_exempt_and_logged(bot):
    r = run(pr(author=bot))
    assert r.returncode == 0
    assert "::notice::" in r.stdout


def test_break_glass_by_maintainer_is_exempt_and_logged(maintainers):
    r = run(pr(author="dave", break_glass_by="carol"), maintainers)
    assert r.returncode == 0
    assert "::warning::" in r.stdout and "carol" in r.stdout


def test_break_glass_self_applied_by_maintainer_is_allowed(maintainers):
    # emergency hotfix: a maintainer may break glass on their own PR; it is still logged
    r = run(pr(author="bob", break_glass_by="bob"), maintainers)
    assert r.returncode == 0
    assert "::warning::" in r.stdout


def test_break_glass_by_non_maintainer_is_blocked(maintainers):
    assert run(pr(author="dave", break_glass_by="dave"), maintainers).returncode == 1


def test_break_glass_without_maintainers_file_is_blocked():
    assert run(pr(author="dave", break_glass_by="carol")).returncode == 1


def test_ghost_issue_author_is_handled():
    payload = pr(issues=[issue()])
    payload["closingIssuesReferences"]["nodes"][0]["author"] = None
    assert run(payload).returncode == 0
