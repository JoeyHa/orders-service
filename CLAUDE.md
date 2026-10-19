# orders-service

Small orders API: users, orders with a `pending → paid | cancelled` lifecycle, and a paid-revenue report. Full design: `docs/design.md`. Run/test commands: `README.md`. Review process: `docs/review-pipeline.md`.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 async (asyncpg) · Alembic · Postgres 16 · pytest + httpx · ruff · Docker · GitHub Actions (CI: lint/test/build, CD: image to GHCR).

## Layout

- `app/api/` routers (`users.py`, `orders.py`) · `app/models.py` ORM · `app/db.py` engine + `SessionDep` · `app/auth.py` `require_api_key` · `app/config.py` env settings
- `migrations/versions/` Alembic · `tests/` real-Postgres tests
- `scripts/` + `.githooks/` pre-push gate · `.claude/` skills, `diff-reviewer` agent, hook settings

## Conventions

1. DB access in routes goes through `SessionDep`. Never import `engine` in app code outside `db.py`.
2. Every write endpoint (POST/PATCH/PUT/DELETE) declares `dependencies=[Depends(require_api_key)]`. Reads are open.
3. Raw SQL only via `sqlalchemy.text()` with bound parameters. Never build SQL with f-strings, `%` or `.format()`.
4. Order status changes check `ALLOWED_TRANSITIONS` and read the row with `with_for_update()` in the same transaction.
5. Schema changes ship a model change and a new migration in the same PR. Never edit a migration already on `main`. `alembic check` must stay clean.
6. Money is integer cents (`amount_cents`). Every int that reaches Postgres (ids, `amount_cents`) is bounded to int4 at the API with `INT4_MAX` from `app/models.py`.
7. Errors are `HTTPException` with an explicit status; unique violations map to 409, missing rows to 404. No 500s for bad input.
8. Config comes only from env through `app/config.py`. Secrets have no defaults.
9. Tests hit real Postgres; no DB mocks. Every new endpoint behavior gets a test.
10. FastAPI dependencies use `Annotated[...]`. `ruff check` and `ruff format --check` stay clean.

Before pushing or opening a PR, run `/pre-pr` (lint, tests, build, diff review). Claude Code blocks push and `gh pr create` until it passes; plain `git push` is blocked too once `git config core.hooksPath .githooks` is set.

If a PR changes something this file states (stack, layout, a convention, commands), update this file in the same PR.

## Goals

Correct, simple order handling: no lost updates, no unauthenticated writes, no data-corrupting migrations.

## Non-goals

Frontend, real user auth/accounts, pagination, multi-tenant, deployment/hosting, caching.
