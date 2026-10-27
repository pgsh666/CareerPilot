"""Account, verification, server session and abuse-control foundations."""
import sqlalchemy as sa
from alembic import op

revision = "0001_accounts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("name", sa.String(24), nullable=False),
        sa.Column("avatar", sa.String(24), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "verification_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
    )
    op.create_index("ix_verification_lookup", "verification_codes", ["email", "purpose", "owner_id", "created_at"])
    op.create_table(
        "rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("rate_buckets")
    op.drop_table("verification_codes")
    op.drop_table("auth_sessions")
    op.drop_table("users")

