async def test_create_user(client, auth):
    r = await client.post("/users", json={"email": "Ann@X.com", "name": "Ann"}, headers=auth)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ann@x.com"
    assert body["name"] == "Ann"
    assert isinstance(body["id"], int)


async def test_duplicate_email_case_insensitive(client, auth):
    await client.post("/users", json={"email": "a@x.com", "name": "A"}, headers=auth)
    r = await client.post("/users", json={"email": "A@X.com", "name": "B"}, headers=auth)
    assert r.status_code == 409


async def test_invalid_email(client, auth):
    r = await client.post("/users", json={"email": "nope", "name": "A"}, headers=auth)
    assert r.status_code == 422


async def test_get_user(client, auth):
    created = (
        await client.post("/users", json={"email": "a@x.com", "name": "A"}, headers=auth)
    ).json()
    r = await client.get(f"/users/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


async def test_get_missing_user(client):
    r = await client.get("/users/999")
    assert r.status_code == 404


async def test_create_user_requires_key(client):
    r = await client.post("/users", json={"email": "a@x.com", "name": "A"})
    assert r.status_code == 401


async def test_user_routes_are_described_in_the_api_docs(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "409" in paths["/users"]["post"]["description"]
    assert "404" in paths["/users/{user_id}"]["get"]["description"]
