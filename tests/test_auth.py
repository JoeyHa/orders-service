import pytest

WRITES = [
    ("post", "/users", {"email": "a@x.com", "name": "A"}),
    ("post", "/orders", {"user_id": 1, "amount_cents": 1}),
    ("patch", "/orders/1", {"status": "paid"}),
]


@pytest.mark.parametrize("method,path,body", WRITES)
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
async def test_writes_require_valid_key(client, method, path, body, headers):
    r = await client.request(method, path, json=body, headers=headers)
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/health", "/orders", "/users/1"])
async def test_reads_are_open(client, path):
    r = await client.get(path)
    assert r.status_code != 401
