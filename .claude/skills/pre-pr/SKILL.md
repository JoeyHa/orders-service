---
name: pre-pr
description: Build, test, and AI-review the branch against main before pushing or opening a PR. Use when asked to "pre-pr", "check before PR", or when a push/PR is blocked by the pre-pr gate.
---

# Pre-PR: build, test, review

Layer 1 of review. Opening a PR (`gh pr create`) is gated on this passing for the current HEAD; pushes are not.

1. **Scope.** `git fetch -q origin main`. If `git diff --quiet origin/main...HEAD`, say "nothing to review" and stop. Uncommitted changes are not reviewed — if `git status --porcelain` is non-empty, tell the user and stop.
2. **Checks.** Run in order; stop at the first failure and report its output tail:
   ```bash
   ruff check . && ruff format --check .
   docker compose up -d && pytest -q
   docker build -q -t orders-service:pre-pr .
   ```
   `pytest` needs `DATABASE_URL` (see `.env.example`); `tests/conftest.py` defaults it to the compose Postgres.
3. **Review.** Spawn the `diff-reviewer` agent with the prompt: "Review origin/main...HEAD." Do not review the diff yourself, and do not pass it your own opinion of the change.
4. **Record.** Write the result for the gate — line 1 the HEAD SHA, line 2 the verdict word from the agent's last line, then the review:
   ```bash
   { git rev-parse HEAD; echo PASS_OR_BLOCK; cat <<'REVIEW'
   <agent output>
   REVIEW
   } > "$(git rev-parse --git-dir)/pre-pr-review"
   ```
   Write `PASS` only if the checks passed and the agent's last line is `VERDICT: PASS`. Never edit the verdict.
5. **Report.** Show the checks summary and the review verbatim. On `BLOCK`, list the blocking findings; the user fixes, commits, and re-runs `/pre-pr`.
