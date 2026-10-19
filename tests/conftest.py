import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://orders:orders@localhost:5433/orders")
os.environ.setdefault("API_KEY", "test-key")

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db import engine
from app.main import app

API_KEY = os.environ["API_KEY"]


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE orders, users RESTART IDENTITY CASCADE"))
    yield
    # each test runs in its own event loop; drop pooled connections bound to this one
    await engine.dispose()
