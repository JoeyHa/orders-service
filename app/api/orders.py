from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import require_api_key
from app.db import SessionDep
from app.models import Order, User

router = APIRouter(tags=["orders"])

OrderStatus = Literal["pending", "paid", "cancelled"]
ALLOWED_TRANSITIONS = {("pending", "paid"), ("pending", "cancelled")}
INT4_MAX = 2_147_483_647


class OrderIn(BaseModel):
    user_id: int
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
async def list_orders(session: SessionDep, user_id: int | None = None) -> Sequence[Order]:
    stmt = select(Order).order_by(Order.id)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    return (await session.scalars(stmt)).all()


@router.patch(
    "/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_api_key)]
)
async def update_order(order_id: int, body: OrderPatch, session: SessionDep) -> Order:
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
