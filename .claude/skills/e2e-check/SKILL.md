---
name: e2e-check
description: Run the real app against real Postgres and exercise the changed endpoints over HTTP. Use when asked to "check end to end", "e2e", or before a PR.
---

# End-to-end check

Unit tests use an in-process client. This runs the real server.

1. Start Postgres and migrate:
   ```bash
   docker compose up -d
   export DATABASE_URL=postgresql+asyncpg://orders:orders@localhost:5433/orders API_KEY=e2e-key
   alembic upgrade head
   docker exec orders-postgres psql -U orders -qc "TRUNCATE orders, users RESTART IDENTITY CASCADE"
   ```
2. Start the server in the background and wait for it:
   ```bash
   uvicorn app.main:app --port 8010 > /tmp/orders-e2e.log 2>&1 &
   until curl -sf localhost:8010/health >/dev/null; do sleep 0.5; done
   ```
3. Baseline flow — every step must return the shown status:
   ```bash
   api() { curl -s -w ' %{http_code}\n' -H 'Content-Type: application/json' -H 'X-API-Key: e2e-key' "$@"; }
   api -d '{"email":"e2e@x.com","name":"E"}' localhost:8010/users            # 201
   api -d '{"user_id":1,"amount_cents":500}' localhost:8010/orders           # 201
   api -X PATCH -d '{"status":"paid"}' localhost:8010/orders/1               # 200
   api -X PATCH -d '{"status":"cancelled"}' localhost:8010/orders/1          # 409
   curl -s -w ' %{http_code}\n' -H 'Content-Type: application/json' \
     -d '{"user_id":1,"amount_cents":1}' localhost:8010/orders                # 401 (no key)
   curl -s -w ' %{http_code}\n' localhost:8010/reports/revenue                # 200, revenue_cents 500
   ```
4. Then exercise every endpoint the branch changed, with a happy path and one bad input each.
5. Stop the server (`kill %1`). Report each request, expected vs actual status and body. Any mismatch = failed check.
