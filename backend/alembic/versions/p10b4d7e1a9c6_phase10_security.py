"""phase10 authentication security and audit

Revision ID: p10b4d7e1a9c6
Revises: p9f3c8d2e7b1
Create Date: 2026-10-09

Adds the Phase 10 security surface:
* users: last_login_at, password_changed_at, token_version (session revocation)
* revoked_tokens: server-side JWT deny-list (logout)
* audit_logs: outcome + request_id columns and supporting indexes
"""

import sqlalchemy as sa
from alembic import op

revision = "p10b4d7e1a9c6"
down_revision = "p9f3c8d2e7b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("password_changed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
    op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])

    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("outcome", sa.String(length=16), nullable=False,
                                   server_default="SUCCESS"))
        batch.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_outcome", "audit_logs", ["outcome"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_outcome", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("request_id")
        batch.drop_column("outcome")
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
        batch.drop_column("password_changed_at")
        batch.drop_column("last_login_at")
