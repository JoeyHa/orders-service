---
name: bug-hunt
description: Hunt for real bugs in the current branch's diff before opening a PR. Use when asked to "hunt bugs", "find bugs", or before a PR.
---

# Bug hunt

Find bugs a user would hit, in what this branch changes. Not style.

1. `git diff origin/main...HEAD` — list every changed function and endpoint.
2. For each, read its callers and what it calls (`grep -rn <name> app tests`). Read the whole function, not just the hunk.
3. Check against `REVIEW.md` "Check, in this order" and the conventions in `CLAUDE.md`.
4. For each suspected bug, prove it: write a failing pytest in `tests/` that reproduces it and run `pytest <file>::<test> -q`. A suspicion you can't reproduce is not reported as a bug — list it under "Unconfirmed" with the line.
5. Report: `N bugs confirmed`, then for each: `file:line`, what breaks, the failing test name. Do not fix unless asked.
