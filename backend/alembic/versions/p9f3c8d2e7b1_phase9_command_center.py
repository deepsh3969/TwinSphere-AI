"""phase9 command center analytics historical intelligence

Revision ID: p9f3c8d2e7b1
Revises: p8d9f4b7a2c6e
Create Date: 2026-10-08 12:00:00.000000

Additive, safe, idempotent (Phase 9 §67):
* new indexes only — analytics/replay range scans (Phase 9 §48):
  - risk_scores(entity_id, created_at)   — risk windows per entity
  - occupancy_records(building_id, created_at) — occupancy windows per building
  - simulation_events(simulation_id, t)  — replay event ordering
  - route_events(simulation_id, created_at) — route history per simulation
  - incidents(severity), incidents(kind) — history facets/filters
No existing data, columns or tables are modified or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p9f3c8d2e7b1'
down_revision: Union[str, None] = 'p8d9f4b7a2c6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, index name, columns) — all additive, created only when missing
_INDEXES = (
    ("risk_scores", "ix_risk_scores_entity_time", ["entity_id", "created_at"]),
    ("occupancy_records", "ix_occupancy_records_building_time", ["building_id", "created_at"]),
    ("simulation_events", "ix_simulation_events_sim_t", ["simulation_id", "t"]),
    ("route_events", "ix_route_events_sim_time", ["simulation_id", "created_at"]),
    ("incidents", "ix_incidents_severity", ["severity"]),
    ("incidents", "ix_incidents_kind", ["kind"]),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table_name, index_name, columns in _INDEXES:
        if table_name not in tables:
            continue
        present = {i["name"] for i in inspector.get_indexes(table_name)}
        if index_name in present:
            continue
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.create_index(index_name, columns, unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table_name, index_name, _columns in reversed(_INDEXES):
        if table_name not in tables:
            continue
        present = {i["name"] for i in inspector.get_indexes(table_name)}
        if index_name not in present:
            continue
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(index_name)
