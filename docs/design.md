# orders-service — Base App + CI/CD Design

**Date:** 2026-10-19

## Purpose

A small FastAPI + Postgres orders API with standard CI/CD: DB writes and transactions, a raw SQL report, endpoint auth, and schema migrations.

## Constraints

- GitHub repo: `orders-service` (public).
- Zero cost: public repo (free Actions minutes), GHCR for images, built-in `GITHUB_TOKEN` only.
- Stack matches `backend/`: Python 3.12, FastAPI, async SQLAlchemy (asyncpg), Alembic, pytest, ruff.

## Layout

```
app/
  main.py         FastAPI app, router include, GET /health
  config.py       pydantic-settings: DATABASE_URL, API_KEY
  db.py           async engine + sessionmaker + get_session dependency
  models.py       User, Order ORM models
  auth.py         require_api_key dependency (X-API-Key header)
  api/
    users.py      user endpoints
    orders.py     order endpoints + revenue report
migrations/       Alembic, one initial migration (users, orders)
tests/            pytest + httpx AsyncClient against real Postgres
Dockerfile
docker-compose.yml   postgres:16 only
pyproject.toml
README.md
.github/workflows/ci.yml
.github/workflows/cd.yml
```

## Data model

- **users**: `id` (PK), `email` (unique, not null), `name`, `created_at`
- **orders**: `id` (PK), `user_id` (FK → users.id, not null), `amount_cents` (int, not null, ≥ 0), `status` (`pending` | `paid` | `cancelled` | `refunded`), `created_at`, `updated_at`

## API

All write endpoints require `X-API-Key` matching `API_KEY` (401 otherwise). Reads are open.

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/health` | `{"status":"ok"}` |
| POST | `/users` | Create user; 409 on duplicate email |
| GET | `/users/{id}` | 404 if missing |
| POST | `/orders` | Create order for existing user (404 if user missing), status `pending` |
| GET | `/orders?user_id=` | List orders, optional filter |
| PATCH | `/orders/{id}` | Update status; only `pending → paid` / `pending → cancelled` / `paid → refunded` allowed, else 409 |
| GET | `/reports/revenue` | Raw SQL (`sqlalchemy.text`, bound params): paid revenue per user, optional `since` date |

Status changes run in a single transaction with a row lock (`SELECT ... FOR UPDATE`) so concurrent updates can't both succeed.

## Error handling

Use FastAPI `HTTPException` with the status codes above. IntegrityError on duplicate email maps to 409. No custom error framework.

## Testing

pytest against a real Postgres (docker-compose locally, service container in CI); migrations applied before tests. One test per endpoint behavior listed above, plus auth (missing/wrong key → 401) and the status-transition rules.

## CI/CD

**`ci.yml`**: on `pull_request` and push to `main`:
- `lint`: `ruff check .` and `ruff format --check .`
- `test`: Postgres 16 service container → `alembic upgrade head` → `pytest`
- `build`: `docker build .`

**`cd.yml`**: on push to `main`, after CI succeeds: build and push `ghcr.io/<owner>/orders-service:<sha>` and `:latest` using `GITHUB_TOKEN` (`packages: write`).

**Branch protection on `main`:** require `lint`, `test`, `build`.

## Out of scope

Frontend, deploy target/hosting, staging/prod environments, Python version matrix, coverage gates, release tagging, pagination, real user auth.
