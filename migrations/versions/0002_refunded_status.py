"""allow refunded order status"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_status", "orders", "status IN ('pending', 'paid', 'cancelled', 'refunded')"
    )


def downgrade() -> None:
    # fails if any order is refunded: those rows have no status to go back to
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_status", "orders", "status IN ('pending', 'paid', 'cancelled')"
    )
