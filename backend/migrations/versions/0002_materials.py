"""Private material files, editable material heads and immutable confirmed versions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision = "0002_materials"
down_revision = "0001_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "material_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("file_type", sa.String(8), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_material_files_owner_id", "material_files", ["owner_id"])
    op.create_table(
        "materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("material_files.id")),
        sa.Column("source", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("extracted_fields", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_message", sa.String(180)),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.UniqueConstraint("owner_id", "kind", "request_key", name="uq_material_request"),
    )
    op.create_index("ix_material_owner_kind_time", "materials", ["owner_id", "kind", "updated_at"])
    op.create_table(
        "material_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("material_id", "number", name="uq_material_version"),
    )
    op.create_index("ix_material_versions_material_id", "material_versions", ["material_id"])


def downgrade():
    op.drop_table("material_versions")
    op.drop_table("materials")
    op.drop_table("material_files")
