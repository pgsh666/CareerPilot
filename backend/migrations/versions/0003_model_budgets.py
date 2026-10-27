"""Persistent cumulative test allowance and monthly model reservations. No paid calls."""
import sqlalchemy as sa
from alembic import op

revision = "0003_model_budgets"
down_revision = "0002_materials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_budgets",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("limit_micro", sa.BigInteger(), nullable=False),
        sa.Column("charged_micro", sa.BigInteger(), nullable=False),
        sa.Column("held_micro", sa.BigInteger(), nullable=False),
        sa.Column("sent_calls", sa.Integer(), nullable=False),
        sa.Column("pending_calls", sa.Integer(), nullable=False),
        sa.Column("max_calls", sa.Integer()),
    )
    op.create_table(
        "model_spends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("month_key", sa.String(32), sa.ForeignKey("model_budgets.key"), nullable=False),
        sa.Column("test_mode", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reserved_micro", sa.BigInteger(), nullable=False),
        sa.Column("charged_micro", sa.BigInteger()),
        sa.Column("fee_source", sa.String(32), nullable=False),
        sa.Column("pricing", sa.JSON(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("cached_tokens", sa.Integer()),
        sa.Column("provider_request_id", sa.String(128)),
        sa.Column("error_code", sa.String(48)),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("duration_ms", sa.Integer()),
        sa.UniqueConstraint("request_key"),
    )


def downgrade():
    op.drop_table("model_spends")
    op.drop_table("model_budgets")
