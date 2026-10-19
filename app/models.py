from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

INT4_MAX = 2_147_483_647  # Postgres integer column max; bound API ints to this


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_orders_amount_nonneg"),
        CheckConstraint(
            "status IN ('pending', 'paid', 'cancelled', 'refunded')", name="ck_orders_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
