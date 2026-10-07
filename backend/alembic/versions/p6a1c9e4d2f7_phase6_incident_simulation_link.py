"""phase6 incident simulation link

Revision ID: p6a1c9e4d2f7
Revises: b3937b6fe73a
Create Date: 2026-10-05 09:45:00.000000

Additive, safe, idempotent: nullable column + index linking an incident to
the emergency simulation that produced it (Phase 6 §33).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p6a1c9e4d2f7'
down_revision: Union[str, None] = 'b3937b6fe73a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("incidents")}
    if "simulation_id" not in cols:
        with op.batch_alter_table("incidents", schema=None) as batch_op:
            batch_op.add_column(sa.Column("simulation_id", sa.String(length=40), nullable=True))
    idx = {i["name"] for i in inspector.get_indexes("incidents")}
    if "ix_incidents_simulation_id" not in idx:
        with op.batch_alter_table("incidents", schema=None) as batch_op:
            batch_op.create_index("ix_incidents_simulation_id", ["simulation_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_index("ix_incidents_simulation_id")
        batch_op.drop_column("simulation_id")
