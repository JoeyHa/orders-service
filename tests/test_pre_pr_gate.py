import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x.com",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(tmp_path, "switch", "-q", "-c", "feature")
    (tmp_path / "f.txt").write_text("change\n")
    git(tmp_path, "add", "f.txt")
    git(tmp_path, "commit", "-q", "-m", "change")
    return tmp_path


def check(repo: Path) -> int:
    return subprocess.run([SCRIPTS / "check-pre-pr.sh"], cwd=repo, capture_output=True).returncode


def write_marker(repo: Path, sha: str, verdict: str) -> None:
    (repo / ".git" / "pre-pr-review").write_text(f"{sha}\n{verdict}\nreview text\n")


def test_blocks_without_review(repo):
    assert check(repo) == 1


def test_passes_with_review_for_head(repo):
    write_marker(repo, git(repo, "rev-parse", "HEAD"), "PASS")
    assert check(repo) == 0


def test_blocks_when_review_blocked(repo):
    write_marker(repo, git(repo, "rev-parse", "HEAD"), "BLOCK")
    assert check(repo) == 1


def test_blocks_when_review_is_for_older_commit(repo):
    write_marker(repo, git(repo, "rev-parse", "HEAD"), "PASS")
    git(repo, "commit", "-q", "--allow-empty", "-m", "another change")
    assert check(repo) == 1


def test_passes_when_nothing_to_review(repo):
    git(repo, "switch", "-q", "main")
    assert check(repo) == 0


def test_passes_when_branch_has_commits_but_no_changes(repo):
    git(repo, "switch", "-q", "-c", "empty", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert check(repo) == 0


def claude_hook(repo: Path, command: str) -> int:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [SCRIPTS / "claude-pre-pr-gate.sh"],
        input=payload,
        text=True,
        capture_output=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)},
    ).returncode


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --fill",
        "cd /repo && gh pr create --draft",
        "ruff check .; gh pr create",
        "  gh  pr  create",
    ],
)
def test_claude_hook_blocks_pr_creation_without_review(repo, command):
    assert claude_hook(repo, command) == 2


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        # pushes are allowed: WIP backup and sharing; review is gated at PR creation
        "git push -u origin feature",
        "cd /repo && git push",
        'echo "gh pr create"',
        "git log --grep='gh pr create'",
        "cat > review.txt <<'EOF'\nfound `*\"gh pr create\"*` on line 5\nEOF",
    ],
)
def test_claude_hook_ignores_other_commands(repo, command):
    assert claude_hook(repo, command) == 0


def test_claude_hook_allows_pr_creation_after_review(repo):
    write_marker(repo, git(repo, "rev-parse", "HEAD"), "PASS")
    assert claude_hook(repo, "gh pr create") == 0
