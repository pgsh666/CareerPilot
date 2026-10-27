"""Approved scoring snapshot, activity writers and account retention metadata."""
import sqlalchemy as sa
from alembic import op

revision = "0006_approved_prd"
down_revision = "0005_scoring_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("former_email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("purged_at", sa.DateTime(), nullable=True))
    op.add_column("trainings", sa.Column("scoring_snapshot", sa.JSON(), nullable=True))
    op.add_column("trainings", sa.Column("writer_lease", sa.String(36), nullable=True))
    op.add_column("trainings", sa.Column("writer_session_id", sa.String(36), nullable=True))
    op.add_column("trainings", sa.Column("writer_seen_at", sa.DateTime(), nullable=True))
    op.add_column("training_questions", sa.Column("dimension_ids", sa.JSON(), nullable=True))
    op.add_column("training_questions", sa.Column("reference_points", sa.JSON(), nullable=True))
    op.add_column("generation_jobs", sa.Column("auth_session_id", sa.String(36), nullable=True))
    op.create_table("model_fee_adjustments",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("spend_id", sa.String(36), sa.ForeignKey("model_spends.id"), nullable=False),
                    sa.Column("evidence_ref", sa.String(128), nullable=False),
                    sa.Column("amount_micro", sa.BigInteger(), nullable=False),
                    sa.Column("previous_amount_micro", sa.BigInteger(), nullable=True),
                    sa.Column("previous_state", sa.String(20), nullable=False),
                    sa.Column("previous_error_code", sa.String(48), nullable=True),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.UniqueConstraint("spend_id", "evidence_ref", name="uq_fee_adjustment_evidence"))
    op.create_index("ix_model_fee_adjustments_spend_id", "model_fee_adjustments", ["spend_id"])


def downgrade():
    op.drop_table("model_fee_adjustments")
    op.drop_column("generation_jobs", "auth_session_id")
    op.drop_column("training_questions", "reference_points")
    op.drop_column("training_questions", "dimension_ids")
    for column in ("writer_seen_at", "writer_session_id", "writer_lease", "scoring_snapshot"):
        op.drop_column("trainings", column)
    op.drop_column("users", "purged_at")
    op.drop_column("users", "former_email")
