"""Persist the deferred scoring state with each training snapshot."""
import sqlalchemy as sa
from alembic import op

revision = "0005_scoring_snapshot"
down_revision = "0004_training"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trainings", sa.Column("scoring_version", sa.String(40), nullable=False,
                                        server_default="rules_pending"))


def downgrade():
    op.drop_column("trainings", "scoring_version")
