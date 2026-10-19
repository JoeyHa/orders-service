# Review guide — orders-service

Owners: @JoeyHa

## What failure looks like here

**It corrupts or leaks data.** Wrong money, a lost or double status update, a write without an API key, a migration that drops or locks data, or user input that reaches SQL or produces a 500.

## Check, in this order

1. **Auth** — a new or changed write endpoint without `require_api_key`.
2. **SQL** — any SQL string built from input; any `text()` without bound params.
3. **Transactions & races** — read-then-write without `with_for_update()`; commits split across a logical change; missing rollback after `IntegrityError`.
4. **Migrations** — model/migration mismatch, edited old migration, `NOT NULL` added without default/backfill, destructive `downgrade`/`upgrade` with no note in the PR.
5. **Input bounds** — values that pass Pydantic but fail in Postgres (int4 overflow, string length, enum values).
6. **Tests** — new behavior with no test, or a test that would pass without the change.
7. **CLAUDE.md** — code that breaks one of its conventions (cite the number), or a change that makes a line in it untrue.

## Risk floors

Minimum risk by path or by changed line, applied by the CI review before any model runs. Models can raise a PR above its floor, never below. Read from `main`.

```json
{
  "paths": {
    "high": [".github/**", "REVIEW.md", "CLAUDE.md", ".claude/**", "review/**", "scripts/**"],
    "medium": ["migrations/**", "app/auth.py", "app/db.py", "app/models.py", "pyproject.toml", "Dockerfile"]
  },
  "content": {
    "medium": ["text\\(", "with_for_update", "require_api_key", "ALLOWED_TRANSITIONS", "\\b(DROP|ALTER|TRUNCATE)\\b"]
  }
}
```

## Evidence

Every finding cites `file:line` and quotes the code that proves it. Trace the call — don't infer behavior from a function or variable name. If you can't point at the line, don't report it.

## Nits

At most 3, labeled `nit:`, never blocking. Skip anything `ruff` already enforces.

## Skip

`migrations/script.py.mako`, `migrations/README`, `.gitignore`, `.dockerignore`, `uv.lock`/lockfiles, `.claude/`.

## Output

Start with the count: `N findings (M blocking)`. Then findings, most severe first. If there is nothing to fix, say exactly `0 findings — nothing to fix.` and stop.
