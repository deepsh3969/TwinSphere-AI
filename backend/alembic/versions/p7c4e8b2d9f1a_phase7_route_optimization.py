"""phase7 route & evacuation optimization

Revision ID: p7c4e8b2d9f1a
Revises: p6a1c9e4d2f7
Create Date: 2026-10-05 12:00:00.000000

Additive, safe, idempotent (Phase 7 §34):
* `evacuation_routes` gains mode/simulation/version/congestion/audit columns
* new `route_events` table — persisted route calculation history (§33),
  consumed later by Phase 9 analytics.
No existing data is modified or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p7c4e8b2d9f1a'
down_revision: Union[str, None] = 'p6a1c9e4d2f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROUTE_COLUMNS = [
    ("simulation_id", sa.String(length=60), ""),
    ("mode", sa.String(length=16), "'balanced'"),
    ("kind", sa.String(length=24), "'evacuation'"),
    ("congestion_score", sa.Float(), "0"),
    ("route_version", sa.Integer(), "1"),
    ("people_at_risk", sa.Integer(), "0"),
    ("created_at", sa.DateTime(), None),
]

ROUTE_EVENTS_TABLE = sa.Table(
    "route_events",
    sa.MetaData(),
    sa.Column("id", sa.String(length=60), primary_key=True),
    sa.Column("route_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("simulation_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("event", sa.String(length=32), nullable=False, server_default="calculated"),
    sa.Column("origin", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("destination", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("mode", sa.String(length=16), nullable=False, server_default="balanced"),
    sa.Column("path", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("distance", sa.Float(), nullable=False, server_default="0"),
    sa.Column("eta_s", sa.Float(), nullable=False, server_default="0"),
    sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"),
    sa.Column("congestion_score", sa.Float(), nullable=False, server_default="0"),
    sa.Column("route_version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("reason", sa.Text(), nullable=False, server_default=""),
    sa.Column("created_at", sa.DateTime(), nullable=False),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "evacuation_routes" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("evacuation_routes")}
        for name, coltype, _default in ROUTE_COLUMNS:
            if name not in cols:
                with op.batch_alter_table("evacuation_routes", schema=None) as batch_op:
                    batch_op.add_column(sa.Column(name, coltype, nullable=True))
        idx = {i["name"] for i in inspector.get_indexes("evacuation_routes")}
        if "ix_evacuation_routes_simulation_id" not in idx:
            with op.batch_alter_table("evacuation_routes", schema=None) as batch_op:
                batch_op.create_index("ix_evacuation_routes_simulation_id",
                                      ["simulation_id"], unique=False)

    if "route_events" not in inspector.get_table_names():
        ROUTE_EVENTS_TABLE.create(op.get_bind())
        with op.batch_alter_table("route_events", schema=None) as batch_op:
            batch_op.create_index("ix_route_events_route_id", ["route_id"], unique=False)
            batch_op.create_index("ix_route_events_simulation_id", ["simulation_id"], unique=False)
            batch_op.create_index("ix_route_events_created_at", ["created_at"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "route_events" in inspector.get_table_names():
        with op.batch_alter_table("route_events", schema=None) as batch_op:
            batch_op.drop_index("ix_route_events_created_at")
            batch_op.drop_index("ix_route_events_simulation_id")
            batch_op.drop_index("ix_route_events_route_id")
        op.drop_table("route_events")
    if "evacuation_routes" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("evacuation_routes")}
        with op.batch_alter_table("evacuation_routes", schema=None) as batch_op:
            if "ix_evacuation_routes_simulation_id" in {i["name"] for i in inspector.get_indexes("evacuation_routes")}:
                batch_op.drop_index("ix_evacuation_routes_simulation_id")
            for name, _coltype, _default in ROUTE_COLUMNS:
                if name in cols:
                    batch_op.drop_column(name)
