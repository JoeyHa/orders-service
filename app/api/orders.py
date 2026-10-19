from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.auth import require_api_key
from app.db import SessionDep
from app.models import INT4_MAX, Order, User

router = APIRouter(tags=["orders"])

OrderStatus = Literal["pending", "paid", "cancelled", "refunded"]
ALLOWED_TRANSITIONS = {("pending", "paid"), ("pending", "cancelled"), ("paid", "refunded")}


class OrderIn(BaseModel):
    user_id: int = Field(ge=1, le=INT4_MAX)
    amount_cents: int = Field(ge=0, le=INT4_MAX)


class OrderPatch(BaseModel):
    status: OrderStatus


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount_cents: int
    status: OrderStatus
    created_at: datetime
    updated_at: datetime


@router.post(
    "/orders", status_code=201, response_model=OrderOut, dependencies=[Depends(require_api_key)]
)
async def create_order(body: OrderIn, session: SessionDep) -> Order:
    if await session.get(User, body.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    order = Order(user_id=body.user_id, amount_cents=body.amount_cents)
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    session: SessionDep, user_id: Annotated[int | None, Query(ge=1, le=INT4_MAX)] = None
) -> Sequence[Order]:
    stmt = select(Order).order_by(Order.id)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    return (await session.scalars(stmt)).all()


@router.patch(
    "/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_api_key)]
)
async def update_order(
    order_id: Annotated[int, Path(ge=1, le=INT4_MAX)], body: OrderPatch, session: SessionDep
) -> Order:
    # row lock held until commit, so concurrent transitions are serialized
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if (order.status, body.status) not in ALLOWED_TRANSITIONS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"cannot change status from {order.status} to {body.status}"
        )
    order.status = body.status
    await session.commit()
    await session.refresh(order)
    return order


REVENUE_SQL = text(
    """
    SELECT u.id AS user_id, u.email, SUM(o.amount_cents) AS revenue_cents
    FROM users u
    JOIN orders o ON o.user_id = u.id
    WHERE o.status = 'paid'
      AND (CAST(:since AS date) IS NULL OR o.created_at >= CAST(:since AS date))
    GROUP BY u.id, u.email
    ORDER BY revenue_cents DESC, u.id
    """
)


class RevenueRow(BaseModel):
    user_id: int
    email: str
    revenue_cents: int


@router.get("/reports/revenue", response_model=list[RevenueRow])
async def revenue_report(session: SessionDep, since: date | None = None) -> list[dict]:
    result = await session.execute(REVENUE_SQL, {"since": since})
    return [dict(row) for row in result.mappings()]
