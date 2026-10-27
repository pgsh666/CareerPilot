"""Private custom avatar data; existing preset values remain valid."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision = "0007_avatar_images"
down_revision = "0006_approved_prd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("avatar_images",
                    sa.Column("id", sa.String(24), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("png_base64", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.UniqueConstraint("owner_id", name="uq_avatar_images_owner"))


def downgrade():
    op.execute("UPDATE users SET avatar = 'default' WHERE avatar LIKE 'upload_%'")
    op.drop_table("avatar_images")
