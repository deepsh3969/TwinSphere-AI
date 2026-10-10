"""phase11 reliability performance and regression suite

Revision ID: p11e5a7c3d8f4
Revises: p10b4d7e1a9c6
Create Date: 2026-10-10 13:00:00.000000

Additive, safe, idempotent (Phase 11): new composite indexes only, for the
filtered+sorted hot paths found by EXPLAIN QUERY PLAN (docs/PERFORMANCE.md):
  - audit_logs(action, created_at)    — security queries by action family
  - audit_logs(outcome, created_at)   — denied/authz monitoring
  - audit_logs(actor, created_at)     — actor-scoped audit queries
  - incidents(severity, started_at)   — history facet + pagination
No existing data, columns or tables are modified or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p11e5a7c3d8f4'
down_revision: Union[str, None] = 'p10b4d7e1a9c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, index name, columns) — all additive, created only when missing
_INDEXES = (
    ("audit_logs", "ix_audit_logs_action_time", ["action", "created_at"]),
    ("audit_logs", "ix_audit_logs_outcome_time", ["outcome", "created_at"]),
    ("audit_logs", "ix_audit_logs_actor_time", ["actor", "created_at"]),
    ("incidents", "ix_incidents_severity_started", ["severity", "started_at"]),
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
