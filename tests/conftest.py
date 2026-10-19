import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://orders:orders@localhost:5433/orders")
os.environ.setdefault("API_KEY", "test-key")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

API_KEY = os.environ["API_KEY"]


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": API_KEY}
