from sqlalchemy import text

from app.db import engine


async def setup_orders(client, auth) -> tuple[int, int]:
    a = (await client.post("/users", json={"email": "a@x.com", "name": "A"}, headers=auth)).json()
    b = (await client.post("/users", json={"email": "b@x.com", "name": "B"}, headers=auth)).json()
    for user, amount, final in [
        (a, 500, "paid"),
        (a, 700, "paid"),
        (a, 9999, "cancelled"),
        (b, 3000, "paid"),
        (b, 8888, None),  # stays pending
    ]:
        o = (
            await client.post(
                "/orders", json={"user_id": user["id"], "amount_cents": amount}, headers=auth
            )
        ).json()
        if final:
            await client.patch(f"/orders/{o['id']}", json={"status": final}, headers=auth)
    return a["id"], b["id"]


async def test_revenue_counts_only_paid(client, auth):
    a, b = await setup_orders(client, auth)
    r = await client.get("/reports/revenue")
    assert r.status_code == 200
    assert r.json() == [
        {"user_id": b, "email": "b@x.com", "revenue_cents": 3000},
        {"user_id": a, "email": "a@x.com", "revenue_cents": 1200},
    ]


async def test_revenue_since_filters_old_orders(client, auth):
    a, b = await setup_orders(client, auth)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE orders SET created_at = '2020-01-01' WHERE user_id = :u"), {"u": a}
        )
    r = await client.get("/reports/revenue", params={"since": "2024-01-01"})
    assert [row["user_id"] for row in r.json()] == [b]


async def test_revenue_empty(client):
    r = await client.get("/reports/revenue")
    assert r.status_code == 200
    assert r.json() == []


async def test_revenue_bad_date(client):
    r = await client.get("/reports/revenue", params={"since": "yesterday"})
    assert r.status_code == 422


async def test_revenue_excludes_refunded(client, auth):
    a, b = await setup_orders(client, auth)
    orders = (await client.get("/orders", params={"user_id": b})).json()
    paid = next(o for o in orders if o["status"] == "paid")
    await client.patch(f"/orders/{paid['id']}", json={"status": "refunded"}, headers=auth)
    r = await client.get("/reports/revenue")
    assert r.json() == [{"user_id": a, "email": "a@x.com", "revenue_cents": 1200}]
