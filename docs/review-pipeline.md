# Review Pipeline

How a change to orders-service gets from a laptop to `main`, and which layer catches what.

**Principle:** every layer is cheaper and faster than the one after it, and catches what it can so the next one sees less. Deterministic checks always run before any LLM. Anything a rule can decide, a rule decides.

**Status:** ✅ built · 🟡 interim · ⬜ designed, not built.

Visual version with diagrams: [`review-pipeline.html`](review-pipeline.html) (open locally in a browser).

---

## Overview

```
Issue (authorized, acceptance criteria)
  │
  ▼
L1  Local /pre-pr ───────────── laptop, advisory, cheap model
  │   lint · test · build · diff review (Haiku)
  ▼
PR opened as draft → marked "ready for review"
  │
  ▼
L2  Issue-link check ────────── deterministic, first, blocks
L3  CI: lint · test · build ─── deterministic, required
  │   (AI layers start only after these are green)
  ▼
L4  Risk: floors → classifier → verifier ──── decides depth + human count
  │
  ▼
L5  AI code review (Quick / Standard / Deep by risk)
  │
  ▼
L6  Human approval (0 / 1 / 2 by risk) ──── never replaced by a bot
  │
  ▼
main
  │
  ▼
L7  Telemetry · internal use · rollback ── regressions feed the eval set ──┐
                                                                          │
        (back to L4/L5: the reviewer is rescored on what it missed) ◄─────┘
```

---

## L1 — Local pre-PR review ✅

**What:** the `/pre-pr` skill runs lint, tests and a Docker build, then spawns the `diff-reviewer` agent (Haiku, read-only tools) on `origin/main...HEAD`. The result is written to `.git/pre-pr-review` keyed to the HEAD SHA. A Claude Code `PreToolUse` hook (`scripts/claude-pre-pr-gate.sh`) blocks `gh pr create` until it passes for that SHA.

**Why:** shrink the loop, not enforce. A finding caught locally is fixed in seconds by someone who still has the context; the same finding in CI becomes a public comment, another push, another review run, another notification.

**Trade-offs:**
- **Advisory by design.** Anyone can skip it (opening the PR outside Claude Code, writing the marker by hand). CI never trusts a local marker — L3+ always run.
- **Reduces CI rounds per PR, not CI runs.** The cost moves to the developer's seat on a cheaper model; it doesn't disappear.
- **Pushes allowed, PR creation gated.** Developers push WIP for backup and sharing; gating every push is friction that gets hooks deleted. Git has no "PR created" hook, so the local gate only covers Claude Code users. CI never reads the local marker; it runs its own review (L5).
- **Review is tied to an exact SHA.** Correct, but every fix re-triggers a full review — see *Review rounds*.
- **Fails open** if the hook itself errors: it runs on every Bash call; failing closed would block all of them.

---

## L2 — Issue-link check ✅

**What:** `.github/workflows/issue-link.yml` fetches the PR's `closingIssuesReferences` via GraphQL; `scripts/check_issue_link.py` decides. No linked, open, authorized issue → blocked. Runs on `pull_request_target` (script from `main`, PR code never checked out). No LLM.

**Solo repo:** separation of duties needs two people. With one maintainer, every PR is self-authored, so each one needs a visible, logged `break-glass` — the exception is made visible instead of hidden.

**Not yet required:** becomes a required check once the first real PR confirms the `pull_request_target` check attaches to the PR.

**Why:** compliance (SOC 2 change management): every production change traces to an authorized request.

**Rules:**
- The issue must be **open** and **authorized** — created by, or labeled `approved` by, someone other than the PR author. Who applied a label comes from the issue timeline (`LabeledEvent.actor`); an unknown actor never counts. A link alone proves traceability, not authorization (anyone can open an empty issue).
- **Exemptions are audited, never silent:**

| Case | Handling |
|---|---|
| Dependabot / Renovate | exempt by bot author; scanners still run |
| Incident hotfix | `break-glass` label applied by a maintainer (`.github/maintainers.txt`, read from `main`), logged as a warning naming who applied it, an issue is expected after the fact (policy; the check only warns) |
| Revert | link the original PR's issue, or break-glass |

**Where the AI comes in:** not here. L5 checks that the diff actually satisfies the issue's acceptance criteria and flags scope creep.

---

## L3 — CI checks ✅

**What:** `ci.yml` — `lint` (ruff), `test` (pytest against Postgres 16, `alembic check`), `build` (docker). Required by branch protection. `cd.yml` publishes to GHCR after green builds on `main`.

**Why first:** never spend tokens reviewing code that doesn't build or pass its tests.

**Trade-off:** AI layers wait for CI → review latency includes CI time. Chosen: cost over latency.

**Trust:** runs on `pull_request` — executes PR code, so it holds **no secrets**.

---

## L4 — Risk: floors → classifier → verifier ✅

**Built:** `review/risk.py` (floors from the `## Risk floors` block in `REVIEW.md`, classifier `claude-haiku-5-5`, verifier `claude-sonnet-5-5`), run by `.github/workflows/ai-review.yml`. Sets a `risk:*` label. Any agent failure fails closed to high. Diffs over 150k chars get a medium floor instead of a partial rating.

Decides **review depth** (L5) and **how many humans** (L6). The asymmetry drives the design: a wrong "low" ships unreviewed risky code; a wrong "high" wastes a human's time.

**Blast radius sets the bar.** Risk is not "how complex is the diff" but "what does it cost if this is wrong":

| Factor | Raises the bar | Lowers it |
|---|---|---|
| Reversibility | migrations, data deletes, published APIs | flag-guarded, one-click rollback |
| Data | money (`amount_cents`), user data, auth | logs, docs, tests |
| Dependents | shared code with many callers, public endpoints | a leaf function, internal tool |
| Detection | silent failure (wrong revenue numbers) | fails loudly, caught by telemetry (L7) |

Expensive code gets **more people and more checks**: higher floor, deeper review, more approvers. Cheap, reversible, observable code gets a lighter bar — that's where L7 earns its keep.

**1. Floors (deterministic, from `REVIEW.md`, read from `main`).** Code owners declare paths and content patterns that always need a human:
- Path rules (script): `migrations/**`, `app/auth.py`, `.github/**`, `REVIEW.md`, `CLAUDE.md`, `.claude/**`, `pyproject.toml` → at least **medium**.
- Content rules (grep, LLM backup): raw SQL (`text(`), lock removal, new endpoints.
- Any PR touching policy files → **high**.
- If floors already say medium/high, skip the classifier and verifier (humans are required anyway).
- Every rule carries a `why` in REVIEW.md (missing one fails closed). The report opens with a one-row table (findings · risk · approvals needed · cost), then a `Where | Rule | Why | Proof` table of the reasons at the deciding level (lower ones collapsed), then a findings table. For a line rule, Where is the `file:line` and the proof is the matching `+`/`-` line text, quoted from the diff by code, never by a model; for a path rule the proof is the changed file. Findings are sorted by rank (blocking, important, nit, pre-existing) with a legend; the rank meanings live once in `review/schema.py` and feed both the model's prompt and the report. The diff-size and non-UTF-8 floors are fixed checks in code and carry no rule or why. A `why` must be non-empty text. Reasons are typed records (`review.risk.Reason`); only `review/github.py` renders them, escaping author-controlled text so it cannot break the table.

**2. Classifier (cheap model).** Rates the PR low / medium / high. Can only **raise** above the floor, never lower.

**3. Verifier (different, stronger model).** Runs only when floors **and** classifier say low.
- **Blind:** never sees the classifier's verdict or reasoning (no anchoring).
- **Adversarial:** "find every reason this needs a human" — a prosecutor, not a second judge.
- **Its decision stands.** Since it only runs on "low", it can only keep or raise. The classifier is effectively a cost filter; the verifier is the gate on the one outcome that removes humans.
- Raising requires `file:line` evidence (prevents escalation creep).

**Records:** decision stored **per commit SHA** — stable across reruns (LLMs are non-deterministic) and an audit trail: models, policy version, verdict, evidence.

**Measured:** classifier/verifier disagreement rate (disagreements are hard cases → human-labeled → eval set), verifier escalation rate, defect rate of "low" PRs, plus a random human audit of ~5% of "low" PRs.

**Known attacks:** PR description steering the classifier ("trivial typo fix") — floors don't read prose; splitting a risky change into many "low" PRs — floors are per path/content, not per size.

---

## L5 — AI code review ✅

**Built:** `review/reviewer.py` via `python -m review` in `ai-review.yml`. Depth by risk: Quick `claude-haiku-5-5`, Standard `claude-sonnet-5-5`, Deep `claude-opus-5-5`. Findings are schema-validated, then **evidence-verified in code** (the quoted code must appear within 3 lines of the cited line; others are reported as unverified, never inline). The summary count is computed by the code, not the model. Posted as a `COMMENT` review — never an approval.

**Sandbox** (`review/agent.py`): a `PreToolUse` hook allowlists Read/Grep/Glob **inside the PR checkout only** (symlinks resolved), Bash/Write/Edit/Web/Agent are removed, `dontAsk` denies anything else, `setting_sources=[]` loads no config from the PR, `GH_TOKEN` is removed from the environment while agents run, and the payload is scanned for credential-shaped strings before posting.

**Auth:** `CLAUDE_CODE_OAUTH_TOKEN` (a personal subscription token) in the `ai-review` environment — fine for this personal learning repo. A shared or production setup would use **workload identity federation** (no stored secret; the identity is the repo's workflow, scoped to one workspace with a budget cap).

**Bootstrap limit:** `pull_request_target` runs the workflow from `main`, so the PR that introduces or changes the reviewer is reviewed by the previous version (or not at all) — which is why `review/**` and `.github/**` are high-risk floors.

**Inputs:** the diff, the linked issue (acceptance criteria), `CLAUDE.md`, `REVIEW.md`, and the files the diff touches.

**Depth by risk:**

| Risk | Depth | Model | Context |
|---|---|---|---|
| low | Quick | cheap | diff only |
| medium | Standard | mid | diff + touched files |
| high | Deep | strongest | cross-file call tracing |

A Quick review that finds something serious **escalates** to Deep and raises the PR's risk. Depth is set by risk; review can raise risk, never lower it.

**Findings:** ranked **important / nit / pre-existing**.
- **Pre-existing** issues are reported separately and never block — blaming a PR for old code is a top noise source.
- Nits capped (`REVIEW.md`: max 3).
- Every finding: `file:line` + quoted code. No inference from names.
- Checks **issue fit**: unmet acceptance criteria, scope creep.
- Checks **`CLAUDE.md` drift**: code breaking a convention, or a change making a line untrue.

**Output contract:** summary starts with a count, or exactly `0 findings — nothing to fix.` A separate check validates this format (review-of-the-reviewer).

**Known decisions are not re-raised.** Trade-offs marked `shortcut:` in code, or findings a human dismissed, are skipped unless the code changed. Repeated findings are the #1 reason teams start ignoring an AI reviewer.

---

## L6 — Human approval ✅

**Built:** `review/approvals.py` via `.github/workflows/approvals.yml`. Low 0 / medium 1 / high 2 (`needs-human` → at least 1); only non-bot, non-author approvals of the current head commit count; an unrated PR is blocked; a maintainer's `break-glass` passes with a logged warning. **Known gap:** `pull_request_review` runs the workflow file from the PR branch — protect `.github/` with a ruleset before relying on it.

**Count by risk:** low = 0, medium = 1, high = 2. GitHub has one approvals number per branch, so a **custom required check** reads the risk (set only by the bot, recomputed on every push) and counts approvals.

**Bots never approve.**
- AI posts comments and check runs only — never an `APPROVE` review.
- "Allow GitHub Actions to create and approve pull requests": **off**.
- Branch protection: **dismiss stale approvals on new commits** and **require approval of the most recent reviewable push**.

**Compliance caveat:** SOC 2 / ISO change management usually requires a second person on every production change. "Low = 0 humans" may not pass audit; the fallback is "low = a human approves, but no deep review is requested".

**Ownership:** `CODEOWNERS` decides **who** must approve a path; `REVIEW.md` decides **what** reviewers look for and the risk floors. `.github/`, `REVIEW.md`, `CLAUDE.md`, `.claude/` are owned by maintainers.

---

## L7 — After merge: telemetry and internal use ⬜

**Review is not the last line of defense.** Regressions should surface fast after merge, through:
- **Telemetry:** error rates, latency, 5xx by endpoint, business signals (e.g. revenue report totals moving unexpectedly). Alert on change, not only on thresholds.
- **Internal use (dogfooding):** the team uses the change before customers do.
- **Progressive delivery:** feature flags and canaries limit who sees a change; one-click rollback limits how long.

**Why it belongs in a review design:** pre-merge rigor and post-merge detection trade off. Fast detection + cheap rollback lets reversible, observable changes take the lighter bar (L4 blast radius). Silent, irreversible changes (migrations, money) can't lean on L8 — they get the full bar.

**Closes the loop:** every regression found here traces back to the PR that caused it → added to the reviewer's eval set (see *Evaluating the reviewer*). The pipeline learns from what it missed.

Not applicable to orders-service yet (no deploy target); designed for when there is one.

---

## Trust boundaries ✅

**The code under review must never control its own review.**

| Job | Trigger | Runs PR code? | Secrets |
|---|---|---|---|
| lint, test, build | `pull_request` | yes | none |
| issue check, risk, AI review | `pull_request_target` | **never** — diff read as data | review token only |

- `pull_request` takes the workflow file **from the PR branch** — a PR could edit the review to `exit 0`.
- `pull_request_target` takes it from `main` and has secrets — so checking out and running PR code there is the classic **"pwn request"**.
- **Policy files are always read from `main`:** `REVIEW.md`, `CLAUDE.md`, `CODEOWNERS`, workflows, agent prompts.
- **Review tokens live in an Environment locked to `main`,** not as repo secrets. A repo secret is readable by anyone with write access (push a branch with a new workflow that prints it). An environment with a "deployment branches: `main` only" rule, used by a `pull_request_target` job (which runs from `main`), is out of reach of any branch.
- Agents reading PR content get **read-only tools, no Bash, no network** — prompt injection in the diff has nothing to exfiltrate or execute.

---

## Review rounds ✅

**Built:** `review/rounds.py`. State is a hidden marker in the bot's own review (markers from anyone else are ignored). Same SHA → stored verdict reused; ancestor → incremental; rebase → full; 3 rounds → `needs-human`. **Not built:** the full pass before merge.

- Store the **last reviewed SHA** per PR; after the first round, review only `last_reviewed..HEAD`.
- The incremental pass still reads touched files in full (new code can break old code).
- Rebase / force-push (last SHA no longer an ancestor) → full review.
- One **full pass before merge** / on ready-for-review.
- **Cap rounds** (e.g. 3). A PR that hits the cap is churning: stop auto-review, hand to a human.
- `concurrency` with `cancel-in-progress`: two quick pushes pay for one review.

---

## Evaluating the reviewer ⬜

- **Eval set from reality:** every revert or incident points to a PR the pipeline missed → replay its diff, expect a finding. Plus classifier/verifier disagreements (human-labeled).
- **Prompts, `REVIEW.md`, tool lists and model IDs are code.** A PR changing any of them must pass the eval before merge.
- **Pin model IDs, never aliases.** An alias (e.g. `model: haiku`, which `.claude/agents/diff-reviewer.md` used before it was pinned) silently moves to a new version — the reviewer changes and nobody rescores.
- **Same issue, two verdicts:** a token-exposure finding got "non-blocking" on one run and "blocking" on the next; the only change between them was documenting the gap. LLM verdicts are non-deterministic and documenting a risk can make it *more* salient. Hence: one stored verdict per SHA, a human override path for blocking checks, and a `REVIEW.md` rule for how documented trade-offs are graded.
- **Metrics:** recall on known misses; precision from the human dismiss rate; format adherence (count-first summary, `file:line` on every finding — Haiku once printed "5 findings" over a list of 6).

---

## Interview cheat sheet

| Question | Short answer |
|---|---|
| If L1 can be skipped, why build it? | It shrinks the loop, not enforces. Cuts CI rounds and PR noise; CI never trusts a local marker. |
| Why not an LLM for the issue check? | Anything a rule can decide, a rule decides — cheaper, faster, deterministic, auditable. |
| How is the verifier independent? | Different model, blind to the first verdict, adversarial prompt. Its decision stands; it can only raise. |
| Why trust an LLM with risk at all? | It can only escalate above owner-defined deterministic floors, never de-escalate. |
| How do you stop a PR gaming its own review? | Policy from `main`; PR code is data; touching policy files = high risk. |
| `pull_request` vs `pull_request_target`? | PR-branch workflow without secrets vs base-branch workflow with secrets. Never run PR code with secrets (pwn request). |
| Prompt injection via the PR? | User text is never evidence; agents get read-only tools, no network. |
| How do you keep developers from ignoring it? | Count-first summaries, nit cap, `file:line` evidence, no re-raising dismissed or documented decisions, pre-existing never blocks. |
| How do you know it's any good? | Eval set from reverts/incidents + disagreements; rescore on any prompt/tool/model change; pinned model IDs. |
| What does it cost per PR? | Deterministic first; AI only after green CI; depth by risk; incremental re-review; cancel in-progress runs. |
| Where do review tokens live? | An Environment locked to `main`, used by a `pull_request_target` job. Repo secrets are readable by anyone who can push a branch. |
| Two runs, two verdicts? | LLM verdicts are non-deterministic: store one per SHA, give blocking checks a human override, define how documented trade-offs are graded. |
| Can a bot approve? | Never. Comments and checks only; stale approvals dismissed on new commits. |
| Fail open or closed? | Open where nothing is at stake (local hook on every command); closed where a miss is expensive. |
| What decides how strict review is? | Blast radius: reversibility, data at stake, dependents, how fast a failure would be noticed. Expensive code gets more people and more checks. |
| Isn't review the last line of defense? | No — telemetry, dogfooding and rollback catch what review misses. Fast detection lets reversible changes take a lighter bar; every regression found becomes an eval case. |
