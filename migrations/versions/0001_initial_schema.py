"""Initial users, transactions, and fraud predictions schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_valid_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_reference", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("transaction_hour", sa.SmallInteger(), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("is_new_device", sa.Boolean(), nullable=False),
        sa.Column("location_type", sa.String(length=50), nullable=False),
        sa.Column("merchant_category", sa.String(length=80), nullable=False),
        sa.Column("account_age_days", sa.Integer(), nullable=False),
        sa.Column("transactions_last_24h", sa.Integer(), nullable=False),
        sa.Column("average_transaction_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_transactions_nonnegative_amount"),
        sa.CheckConstraint("transaction_hour BETWEEN 0 AND 23", name="ck_transactions_valid_hour"),
        sa.CheckConstraint("account_age_days >= 0", name="ck_transactions_nonnegative_age"),
        sa.CheckConstraint("transactions_last_24h >= 0", name="ck_transactions_nonnegative_count"),
        sa.CheckConstraint("average_transaction_amount >= 0", name="ck_transactions_nonnegative_average"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_transactions_transaction_reference", "transactions", ["transaction_reference"], unique=True)
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"], unique=False)

    op.create_table(
        "fraud_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("predicted_class", sa.SmallInteger(), nullable=False),
        sa.Column("prediction_label", sa.String(length=20), nullable=False),
        sa.Column("fraud_probability", sa.Numeric(8, 6), nullable=False),
        sa.Column("genuine_probability", sa.Numeric(8, 6), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("predicted_class IN (0, 1)", name="ck_fraud_predictions_valid_class"),
        sa.CheckConstraint("risk_level IN ('LOW', 'MEDIUM', 'HIGH')", name="ck_fraud_predictions_valid_risk"),
        sa.CheckConstraint("fraud_probability BETWEEN 0 AND 1", name="ck_fraud_predictions_valid_fraud_probability"),
        sa.CheckConstraint("genuine_probability BETWEEN 0 AND 1", name="ck_fraud_predictions_valid_genuine_probability"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fraud_predictions_transaction_id", "fraud_predictions", ["transaction_id"], unique=True)


def downgrade():
    op.drop_index("ix_fraud_predictions_transaction_id", table_name="fraud_predictions")
    op.drop_table("fraud_predictions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_index("ix_transactions_transaction_reference", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
