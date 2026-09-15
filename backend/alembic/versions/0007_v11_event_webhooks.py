"""v11 durable event webhooks

Revision ID: 0007_v11_event_webhooks
Revises: 0006_v11_repository_delivery
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_v11_event_webhooks"
down_revision = "0006_v11_repository_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_webhook_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("target_url", sa.String(1000), nullable=False),
        sa.Column("event_pattern", sa.String(180), nullable=False, server_default="*"),
        sa.Column("secret_ref", sa.String(500), nullable=False, server_default=""),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("backoff_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_event_webhook_endpoints_organization_id", "event_webhook_endpoints", ["organization_id"])
    op.create_index("ix_event_webhook_endpoints_company_id", "event_webhook_endpoints", ["company_id"])

    op.create_table(
        "event_webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("event_webhook_endpoints.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("company_events.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_event_webhook_deliveries_organization_id", "event_webhook_deliveries", ["organization_id"])
    op.create_index("ix_event_webhook_deliveries_endpoint_id", "event_webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_event_webhook_deliveries_event_id", "event_webhook_deliveries", ["event_id"])
    op.create_index("ix_event_webhook_deliveries_status", "event_webhook_deliveries", ["status"])
    op.create_index("ix_event_webhook_deliveries_next_attempt_at", "event_webhook_deliveries", ["next_attempt_at"])
    op.create_index("ix_event_webhook_deliveries_created_at", "event_webhook_deliveries", ["created_at"])


def downgrade():
    op.drop_table("event_webhook_deliveries")
    op.drop_table("event_webhook_endpoints")
