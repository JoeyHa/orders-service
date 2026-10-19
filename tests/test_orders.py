import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def user_id(client, auth) -> int:
    r = await client.post("/users", json={"email": "a@x.com", "name": "A"}, headers=auth)
    return r.json()["id"]


async def make_order(client, auth, user_id, amount=1000) -> dict:
    r = await client.post(
        "/orders", json={"user_id": user_id, "amount_cents": amount}, headers=auth
    )
    assert r.status_code == 201
    return r.json()


async def test_create_order(client, auth, user_id):
    order = await make_order(client, auth, user_id)
    assert order["status"] == "pending"
    assert order["amount_cents"] == 1000


async def test_create_order_unknown_user(client, auth):
    r = await client.post("/orders", json={"user_id": 999, "amount_cents": 1}, headers=auth)
    assert r.status_code == 404


@pytest.mark.parametrize("amount", [-1, 2_147_483_648])
async def test_create_order_amount_out_of_range(client, auth, user_id, amount):
    r = await client.post(
        "/orders", json={"user_id": user_id, "amount_cents": amount}, headers=auth
    )
    assert r.status_code == 422


async def test_list_orders_filter(client, auth, user_id):
    other = (
        await client.post("/users", json={"email": "b@x.com", "name": "B"}, headers=auth)
    ).json()["id"]
    await make_order(client, auth, user_id)
    await make_order(client, auth, other)
    all_orders = (await client.get("/orders")).json()
    mine = (await client.get("/orders", params={"user_id": user_id})).json()
    assert len(all_orders) == 2
    assert [o["user_id"] for o in mine] == [user_id]


@pytest.mark.parametrize("target", ["paid", "cancelled"])
async def test_pending_transitions(client, auth, user_id, target):
    order = await make_order(client, auth, user_id)
    r = await client.patch(f"/orders/{order['id']}", json={"status": target}, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == target


@pytest.mark.parametrize(
    "first,second", [("paid", "cancelled"), ("cancelled", "paid"), ("paid", "pending")]
)
async def test_invalid_transitions(client, auth, user_id, first, second):
    order = await make_order(client, auth, user_id)
    await client.patch(f"/orders/{order['id']}", json={"status": first}, headers=auth)
    r = await client.patch(f"/orders/{order['id']}", json={"status": second}, headers=auth)
    assert r.status_code == 409


async def test_patch_missing_order(client, auth):
    r = await client.patch("/orders/999", json={"status": "paid"}, headers=auth)
    assert r.status_code == 404


async def test_patch_unknown_status(client, auth, user_id):
    order = await make_order(client, auth, user_id)
    r = await client.patch(f"/orders/{order['id']}", json={"status": "shipped"}, headers=auth)
    assert r.status_code == 422


async def test_concurrent_transitions_one_wins(client, auth, user_id, monkeypatch):
    order = await make_order(client, auth, user_id)
    url = f"/orders/{order['id']}"

    # delay each commit so both requests read the order before either writes
    original_commit = AsyncSession.commit

    async def slow_commit(self):
        await asyncio.sleep(0.2)
        await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", slow_commit)
    r1, r2 = await asyncio.gather(
        client.patch(url, json={"status": "paid"}, headers=auth),
        client.patch(url, json={"status": "cancelled"}, headers=auth),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]


async def test_refund_paid_order(client, auth, user_id):
    order = await make_order(client, auth, user_id)
    url = f"/orders/{order['id']}"
    await client.patch(url, json={"status": "paid"}, headers=auth)
    r = await client.patch(url, json={"status": "refunded"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "refunded"


@pytest.mark.parametrize(
    "path", [[], ["cancelled"], ["paid", "refunded"]], ids=["pending", "cancelled", "refunded"]
)
async def test_refund_only_from_paid(client, auth, user_id, path):
    order = await make_order(client, auth, user_id)
    url = f"/orders/{order['id']}"
    for step in path:
        assert (await client.patch(url, json={"status": step}, headers=auth)).status_code == 200
    r = await client.patch(url, json={"status": "refunded"}, headers=auth)
    assert r.status_code == 409


@pytest.mark.parametrize("target", ["pending", "paid", "cancelled"])
async def test_refunded_is_final(client, auth, user_id, target):
    order = await make_order(client, auth, user_id)
    url = f"/orders/{order['id']}"
    for step in ["paid", "refunded"]:
        assert (await client.patch(url, json={"status": step}, headers=auth)).status_code == 200
    r = await client.patch(url, json={"status": target}, headers=auth)
    assert r.status_code == 409


async def test_concurrent_refunds_one_wins(client, auth, user_id, monkeypatch):
    order = await make_order(client, auth, user_id)
    url = f"/orders/{order['id']}"
    await client.patch(url, json={"status": "paid"}, headers=auth)

    original_commit = AsyncSession.commit

    async def slow_commit(self):
        await asyncio.sleep(0.2)
        await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", slow_commit)
    r1, r2 = await asyncio.gather(
        client.patch(url, json={"status": "refunded"}, headers=auth),
        client.patch(url, json={"status": "refunded"}, headers=auth),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
