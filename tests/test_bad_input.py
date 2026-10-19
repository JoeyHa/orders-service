import pytest

TOO_BIG = 2**31


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", f"/users/{TOO_BIG}", None),
        ("get", f"/orders?user_id={TOO_BIG}", None),
        ("patch", f"/orders/{TOO_BIG}", {"status": "paid"}),
        ("post", "/orders", {"user_id": TOO_BIG, "amount_cents": 1}),
    ],
)
async def test_ids_beyond_int4_are_422(client, auth, method, path, body):
    r = await client.request(method, path, json=body, headers=auth)
    assert r.status_code == 422


@pytest.mark.parametrize(
    "body", [{"email": "a@x.com", "name": "a\x00b"}, {"email": "n\x00@x.com", "name": "A"}]
)
async def test_nul_byte_in_user_fields_is_422(client, auth, body):
    r = await client.post("/users", json=body, headers=auth)
    assert r.status_code == 422


async def test_non_ascii_api_key_is_401(client):
    r = await client.post(
        "/users", json={"email": "a@x.com", "name": "A"}, headers={"X-API-Key": "tést".encode()}
    )
    assert r.status_code == 401
