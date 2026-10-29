"""Add append-only review audit events.

Revision ID: a41b2c7d9e10
Revises: 362e67e20995
"""
from alembic import op
import sqlalchemy as sa


revision = "a41b2c7d9e10"
down_revision = "362e67e20995"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("fraud_prediction_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("previous_review_status", sa.String(length=20), nullable=True),
        sa.Column("new_review_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_audit_events_created_at_id",
        "audit_events",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_audit_events_actor_user_id",
        "audit_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_audit_events_transaction_id",
        "audit_events",
        ["transaction_id"],
    )


def downgrade():
    op.drop_index("ix_audit_events_transaction_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at_id", table_name="audit_events")
    op.drop_table("audit_events")
