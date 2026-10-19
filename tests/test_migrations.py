import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import engine


async def test_tables_exist():
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert {"users", "orders"} <= set(names)


async def test_negative_amount_rejected_by_db():
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (email, name) VALUES ('a@x.com', 'A')"))
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO orders (user_id, amount_cents) VALUES (1, -1)"))
