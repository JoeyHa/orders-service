"""CI entry point: `python -m review`. Runs from the main checkout; the PR is data in $PR_DIR."""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from review.github import SecretLeak, build_review, post_review, risk_labels, set_labels
from review.policy import load_floors
from review.reviewer import review_pr
from review.risk import decide_risk
from review.rounds import RoundPlan, parse_markers, plan_round
from review.schema import max_level


@contextmanager
def without_github_token():
    """Agents inherit the environment; the token that can write to the repo stays out of it."""
    saved = {k: os.environ.pop(k) for k in ("GH_TOKEN", "GITHUB_TOKEN") if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


async def run_review(io, *, head_sha: str, policy: dict, decide=decide_risk, review=review_pr):
    markers = parse_markers(io.get_reviews())
    plan = plan_round(markers, head_sha, is_ancestor=io.is_ancestor)
    if plan.action == "reuse":
        print(f"verdict for {head_sha} already recorded: {plan.prior.verdict}")
        io.set_labels(
            risk_labels(plan.prior.risk, needs_human=plan.prior.human)
        )  # recover a failed label
        return 1 if plan.prior.verdict == "block" else 0
    if plan.action == "cap":
        print("review round cap reached; handing to a human")
        io.set_labels(risk_labels(plan.prior.risk, needs_human=True))
        return 0

    if plan.action == "incremental" and io.has_merges_since(plan.base):
        # a merge from main brings code that is not the PR's into base..HEAD
        # shortcut: full re-review after such a merge; a merge-tree interdiff would cost less
        plan = RoundPlan("full", plan.round)
    human_before = any(m.human for m in markers)

    full_diff = io.full_diff()
    diff = io.incremental_diff(plan.base) if plan.action == "incremental" else full_diff
    pr_text, issue_text = io.pr_text(), io.issue_text()
    root = io.root

    with without_github_token():
        risk = await decide(full_diff, load_floors(policy["review_md"]), pr_text=pr_text, root=root)
        result = await review(
            diff, pr_text=pr_text, issue_text=issue_text, risk_level=risk.level,
            review_md=policy["review_md"], claude_md=policy["claude_md"], root=root,
        )  # fmt: skip
    result.risk_level = max_level(risk.level, result.risk_level)
    result.cost_usd += risk.cost_usd

    for f in result.unverified:  # one JSON line: model text cannot start a workflow command
        print("unverified finding:", json.dumps(f.model_dump()))

    try:
        payload = build_review(
            result, head_sha=head_sha, plan=plan, risk_reasons=risk.reasons,
            diff=full_diff, human_before=human_before,
        )  # fmt: skip
    except SecretLeak as e:
        print(f"::error::{e}")
        return 1
    io.post(payload)
    needs_human = human_before or result.needs_human  # sticky
    io.set_labels(risk_labels(result.risk_level, needs_human=needs_human))
    return 1 if result.blocking else 0


class GhIo:
    """Real GitHub + git access for the CI job."""

    def __init__(self, repo: str, pr: int, pr_dir: Path):
        self.repo, self.pr, self.root = repo, pr, pr_dir

    def _out(self, *cmd: str) -> str:
        # bytes, not text=True: text mode turns a lone \r into \n and splits diff lines
        return subprocess.run(cmd, capture_output=True, check=True).stdout.decode(
            "utf-8", "replace"
        )

    def get_reviews(self):
        pages = json.loads(self._out("gh", "api", "--paginate", "--slurp",
                                     f"repos/{self.repo}/pulls/{self.pr}/reviews"))  # fmt: skip
        return [review for page in pages for review in page]

    def _pr(self):
        return json.loads(self._out("gh", "pr", "view", str(self.pr), "--repo", self.repo,
                                    "--json", "title,body,closingIssuesReferences"))  # fmt: skip

    def pr_text(self):
        pr = self._pr()
        return f"{pr['title']}\n\n{pr['body']}"

    def issue_text(self):
        issues = self._pr()["closingIssuesReferences"]
        bodies = [self._out("gh", "issue", "view", str(i["number"]), "--repo", self.repo,
                            "--json", "title,body", "--jq", '.title + "\\n\\n" + .body')
                  for i in issues]  # fmt: skip
        return "\n\n---\n\n".join(bodies) or "(no linked issue)"

    def full_diff(self):
        return self._out("gh", "pr", "diff", str(self.pr), "--repo", self.repo)

    def incremental_diff(self, base: str):
        return self._out("git", "-C", str(self.root), "diff", f"{base}..HEAD")

    def has_merges_since(self, base: str) -> bool:
        return bool(
            self._out("git", "-C", str(self.root), "rev-list", "--merges", f"{base}..HEAD").strip()
        )

    def is_ancestor(self, a: str, b: str) -> bool:
        cmd = ["git", "-C", str(self.root), "merge-base", "--is-ancestor", a, b]
        return subprocess.run(cmd, capture_output=True).returncode == 0

    def post(self, payload):
        post_review(self.repo, self.pr, payload)

    def set_labels(self, labels):
        set_labels(self.repo, self.pr, labels)


def main() -> int:
    io = GhIo(os.environ["GITHUB_REPOSITORY"], int(os.environ["PR_NUMBER"]),
              Path(os.environ["PR_DIR"]).resolve())  # fmt: skip
    policy = {
        "review_md": Path("REVIEW.md").read_text(),
        "claude_md": Path("CLAUDE.md").read_text(),
    }
    return asyncio.run(run_review(io, head_sha=os.environ["HEAD_SHA"], policy=policy))


if __name__ == "__main__":
    sys.exit(main())
