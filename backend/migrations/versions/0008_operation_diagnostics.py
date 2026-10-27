"""Persist content-free task and model-call diagnostics."""
import sqlalchemy as sa
from alembic import op

revision = "0008_operation_diagnostics"
down_revision = "0007_avatar_images"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_jobs", sa.Column("diagnostic", sa.JSON(), nullable=True))
    op.add_column("model_spends", sa.Column("diagnostic", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("model_spends", "diagnostic")
    op.drop_column("generation_jobs", "diagnostic")
