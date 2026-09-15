"""v6 baseline schema, scoped to the tables that existed at the baseline.

Revision ID: 0001_baseline
Revises:

The original prototype baseline called ``Base.metadata.create_all()`` without a
``tables`` argument.  Because Alembic imports the *current* model metadata,
that made a fresh install accidentally create future-version tables before
those versioned migrations ran.  Keep the historical baseline metadata-driven
for compatibility, but pin it to the exact v6 table set so the migration chain
is deterministic on fresh databases.
"""
from alembic import op
from app.db.base import Base
import app.models  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

BASELINE_TABLES = [
    "organizations",
    "companies",
    "departments",
    "members",
    "agents",
    "projects",
    "tasks",
    "knowledge_documents",
    "approvals",
    "inbox_items",
    "missions",
    "workflows",
    "workflow_runs",
    "automations",
    "sops",
    "decisions",
    "conversations",
    "conversation_messages",
    "customers",
    "customer_agent_assignments",
    "reports",
    "analytics_metrics",
    "audit_events",
    "integrations",
    "skills",
    "tools",
    "marketplace_templates",
    "subscriptions",
    "organization_settings",
    "role_bindings",
    "permission_policies",
    "users",
    "user_organization_access",
    "api_keys",
    "knowledge_chunks",
    "background_jobs",
]


def _tables():
    return [Base.metadata.tables[name] for name in BASELINE_TABLES]


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), tables=_tables(), checkfirst=True)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_tables())), checkfirst=True)
