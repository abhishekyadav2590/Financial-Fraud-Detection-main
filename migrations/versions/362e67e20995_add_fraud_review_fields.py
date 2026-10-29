"""Add fraud review fields

Revision ID: 362e67e20995
Revises: 0001_initial_schema
Create Date: 2026-08-15 16:03:51.327546

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '362e67e20995'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fraud_predictions') as batch_op:
        batch_op.add_column(
            sa.Column('review_status', sa.String(length=20), server_default='PENDING', nullable=False),
        )
        batch_op.add_column(
            sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        )
        batch_op.add_column(
            sa.Column('review_note', sa.Text(), nullable=True),
        )
        batch_op.create_check_constraint(
            'ck_fraud_predictions_valid_review_status',
            "review_status IN ('PENDING', 'REVIEWED', 'ESCALATED', 'CLEARED')",
        )
        batch_op.create_foreign_key(
            'fk_fraud_predictions_reviewed_by_user_id_users',
            'users',
            ['reviewed_by_user_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_fraud_predictions_review_status',
            ['review_status'],
            unique=False,
        )
        batch_op.create_index(
            'ix_fraud_predictions_reviewed_by_user_id',
            ['reviewed_by_user_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('fraud_predictions') as batch_op:
        batch_op.drop_index('ix_fraud_predictions_reviewed_by_user_id')
        batch_op.drop_index('ix_fraud_predictions_review_status')
        batch_op.drop_constraint(
            'fk_fraud_predictions_reviewed_by_user_id_users',
            type_='foreignkey',
        )
        batch_op.drop_constraint(
            'ck_fraud_predictions_valid_review_status',
            type_='check',
        )
        batch_op.drop_column('review_note')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by_user_id')
        batch_op.drop_column('review_status')
