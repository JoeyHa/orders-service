# orders-service

Small orders API: users, orders with a pending → paid/cancelled lifecycle, and a revenue report.

## Run locally

```bash
docker compose up -d                 # Postgres on localhost:5433
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set API_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

## Test

```bash
pytest
ruff check . && ruff format --check .
```

## Before opening a PR

Run `/pre-pr` in Claude Code: lint, tests, Docker build, then a review of your branch against `main` by the `diff-reviewer` agent (Haiku). Claude Code blocks `gh pr create` until it passes for your current commit. Pushes are not gated.

## API

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | – |
| POST | `/users` | `X-API-Key` |
| GET | `/users/{id}` | – |
| POST | `/orders` | `X-API-Key` |
| GET | `/orders?user_id=` | – |
| PATCH | `/orders/{id}` | `X-API-Key` |
| GET | `/reports/revenue?since=YYYY-MM-DD` | – |

## Docker

```bash
docker build -t orders-service .
docker run --rm -e DATABASE_URL=... -e API_KEY=... orders-service alembic upgrade head
docker run -p 8000:8000 -e DATABASE_URL=... -e API_KEY=... orders-service
```

Images are published to `ghcr.io/joeyha/orders-service` on every green build of `main`.
