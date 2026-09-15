"""v7 execution and SaaS layer

Revision ID: 0002_v7_execution_saas
Revises: 0001_baseline

This historical migration remains metadata-driven, but is pinned to the exact
v7 table set.  That prevents current/future model metadata from leaking into a
fresh historical migration run.
"""
from alembic import op
from app.db.base import Base
import app.models  # noqa: F401

revision = "0002_v7_execution_saas"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

V7_TABLES = [
    "knowledge_vectors",
    "workflow_step_runs",
    "usage_events",
    "billing_invoices",
    "customer_portal_users",
    "customer_project_assignments",
    "nina_command_logs",
]


def _tables():
    return [Base.metadata.tables[name] for name in V7_TABLES]


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_tables(), checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("ALTER TABLE knowledge_vectors ADD COLUMN IF NOT EXISTS embedding vector(384)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_vectors_embedding_hnsw "
            "ON knowledge_vectors USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade():
    # Keep the historical downgrade conservative but scoped: no baseline or
    # later-version table can be removed accidentally.
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_tables())), checkfirst=True)
