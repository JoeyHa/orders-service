---
name: simplify-diff
description: Shrink the current branch's diff without changing behavior — reuse existing helpers, delete dead code. Use when asked to "simplify the diff" or before a PR.
---

# Simplify the diff

Goal: same behavior, fewer lines.

1. `git diff origin/main...HEAD`.
2. Look for, in order:
   - Code that duplicates an existing helper: `SessionDep`, `require_api_key`, `ALLOWED_TRANSITIONS`, `INT4_MAX`, existing Pydantic schemas.
   - Dead code: unused imports, params, branches, schemas, fixtures.
   - Options, config or abstractions nobody uses yet.
   - Tests that assert the same thing twice.
3. Apply each simplification, then run `pytest -q && ruff check . && ruff format --check .`. If anything fails, revert that change.
4. Report: lines removed, and one line per change. Never change behavior or delete a test that covers behavior.
