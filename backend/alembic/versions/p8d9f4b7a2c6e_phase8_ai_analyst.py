"""phase8 ai analyst decision support

Revision ID: p8d9f4b7a2c6e
Revises: p7c4e8b2d9f1a
Create Date: 2026-10-06 12:00:00.000000

Additive, safe, idempotent (Phase 8 §57):
* new `ai_analyses` table — persisted analyst briefs (Phase 9 input)
* new `ai_recommendations` table — analyst cards + human decision state
* new `ai_evidence` table — grounding evidence behind each analysis
No existing data is modified or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p8d9f4b7a2c6e'
down_revision: Union[str, None] = 'p7c4e8b2d9f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AI_ANALYSES_TABLE = sa.Table(
    "ai_analyses",
    sa.MetaData(),
    sa.Column("id", sa.String(length=60), primary_key=True),
    sa.Column("mode", sa.String(length=16), nullable=False, server_default="CAMPUS"),
    sa.Column("severity", sa.String(length=16), nullable=False, server_default="LOW"),
    sa.Column("priority", sa.String(length=16), nullable=False, server_default="LOW"),
    sa.Column("status", sa.String(length=24), nullable=False, server_default="completed"),
    sa.Column("source", sa.String(length=24), nullable=False, server_default="local_fallback"),
    sa.Column("provider", sa.String(length=24), nullable=False, server_default="deterministic"),
    sa.Column("model", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("title", sa.String(length=160), nullable=False, server_default=""),
    sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
    sa.Column("confidence_level", sa.String(length=16), nullable=False, server_default="LOW"),
    sa.Column("question", sa.String(length=500), nullable=False, server_default=""),
    sa.Column("context_signature", sa.String(length=40), nullable=False, server_default=""),
    sa.Column("simulation_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("cached", sa.Boolean(), nullable=False, server_default="0"),
    sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
    sa.Column("created_at", sa.DateTime(), nullable=False),
)

AI_RECOMMENDATIONS_TABLE = sa.Table(
    "ai_recommendations",
    sa.MetaData(),
    sa.Column("id", sa.String(length=60), primary_key=True),
    sa.Column("analysis_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("category", sa.String(length=24), nullable=False, server_default="GENERAL"),
    sa.Column("action", sa.String(length=300), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False, server_default=""),
    sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
    sa.Column("requires_human_approval", sa.Boolean(), nullable=False, server_default="1"),
    sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
    sa.Column("decided_at", sa.DateTime(), nullable=True),
    sa.Column("decided_by", sa.String(length=64), nullable=False, server_default=""),
    sa.Column("created_at", sa.DateTime(), nullable=False),
)

AI_EVIDENCE_TABLE = sa.Table(
    "ai_evidence",
    sa.MetaData(),
    sa.Column("id", sa.String(length=80), primary_key=True),
    sa.Column("analysis_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("label", sa.String(length=200), nullable=False),
    sa.Column("source_type", sa.String(length=24), nullable=False, server_default="campus"),
    sa.Column("source_id", sa.String(length=60), nullable=False, server_default=""),
    sa.Column("metric", sa.String(length=40), nullable=False, server_default=""),
    sa.Column("value", sa.Text(), nullable=False, server_default=""),
    sa.Column("unit", sa.String(length=16), nullable=False, server_default=""),
    sa.Column("severity", sa.String(length=16), nullable=False, server_default="INFO"),
    sa.Column("timestamp", sa.String(length=40), nullable=False, server_default=""),
    sa.Column("age_seconds", sa.Float(), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("detail", sa.Text(), nullable=False, server_default=""),
    sa.Column("created_at", sa.DateTime(), nullable=False),
)

_TABLES = (
    ("ai_analyses", AI_ANALYSES_TABLE, [
        "ix_ai_analyses_mode", "ix_ai_analyses_severity", "ix_ai_analyses_created_at",
        "ix_ai_analyses_context_signature", "ix_ai_analyses_simulation_id",
    ]),
    ("ai_recommendations", AI_RECOMMENDATIONS_TABLE, [
        "ix_ai_recommendations_analysis_id", "ix_ai_recommendations_priority",
        "ix_ai_recommendations_status", "ix_ai_recommendations_created_at",
    ]),
    ("ai_evidence", AI_EVIDENCE_TABLE, [
        "ix_ai_evidence_analysis_id", "ix_ai_evidence_created_at",
    ]),
)

_INDEX_COLUMNS = {
    "ix_ai_analyses_mode": ["mode"],
    "ix_ai_analyses_severity": ["severity"],
    "ix_ai_analyses_created_at": ["created_at"],
    "ix_ai_analyses_context_signature": ["context_signature"],
    "ix_ai_analyses_simulation_id": ["simulation_id"],
    "ix_ai_recommendations_analysis_id": ["analysis_id"],
    "ix_ai_recommendations_priority": ["priority"],
    "ix_ai_recommendations_status": ["status"],
    "ix_ai_recommendations_created_at": ["created_at"],
    "ix_ai_evidence_analysis_id": ["analysis_id"],
    "ix_ai_evidence_created_at": ["created_at"],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, table, indexes in _TABLES:
        if table_name not in inspector.get_table_names():
            table.create(op.get_bind())
            present: set[str] = set()
        else:
            present = {i["name"] for i in inspector.get_indexes(table_name)}
        for index_name in indexes:
            if index_name not in present and index_name in _INDEX_COLUMNS:
                with op.batch_alter_table(table_name, schema=None) as batch_op:
                    batch_op.create_index(index_name, _INDEX_COLUMNS[index_name],
                                           unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()
    for table_name, table, indexes in reversed(_TABLES):
        if table_name in existing:
            op.drop_table(table_name)
