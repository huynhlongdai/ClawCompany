"""A2A: agent thuê ngoài (external_agents) + seat mở cho bên ngoài (a2a_exposures)."""
import sqlalchemy as sa
from alembic import op

revision = "0037_a2a"
down_revision = "0036_core_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("card_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("auth_header", sa.Text(), nullable=False, server_default=""),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_external_agents_organization_id", "external_agents", ["organization_id"])
    op.create_table(
        "a2a_exposures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("token_prefix", sa.String(length=24), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_a2a_exposures_organization_id", "a2a_exposures", ["organization_id"])
    op.create_index("ix_a2a_exposures_agent_id", "a2a_exposures", ["agent_id"], unique=True)


def downgrade() -> None:
    op.drop_table("a2a_exposures")
    op.drop_table("external_agents")
