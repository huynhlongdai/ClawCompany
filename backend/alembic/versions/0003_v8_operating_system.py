"""v8 operating system layer

Revision ID: 0003_v8_operating_system
Revises: 0002_v7_execution_saas

The original v8 prototype used unscoped ``Base.metadata.create_all``.  This
migration is now pinned to the exact v8 table set so a fresh migration chain is
stable even when newer model modules are imported.
"""
from alembic import op
from app.db.base import Base
import app.models  # noqa: F401

revision = "0003_v8_operating_system"
down_revision = "0002_v7_execution_saas"
branch_labels = None
depends_on = None

V8_TABLES = [
    "agent_provisioning_jobs",
    "company_provisioning_jobs",
    "nina_execution_plans",
    "nina_plan_steps",
    "runtime_events",
    "customer_chat_bindings",
    "workflow_graph_versions",
    "usage_meter_rules",
]


def _tables():
    return [Base.metadata.tables[name] for name in V8_TABLES]


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), tables=_tables(), checkfirst=True)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_tables())), checkfirst=True)
