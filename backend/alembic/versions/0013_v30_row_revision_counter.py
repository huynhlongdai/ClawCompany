"""v30 monotonic row revision counters for guarded writes

Revision ID: 0013_v30_row_revision_counter
Revises: 0012_v16_agent_collaboration_mesh

v27, v28 and v29 each avoided a migration and each wrote down the same
consequence: revision tokens built from ``updated_at`` cannot separate two
writes that land inside one clock tick. This adds the column that can.

The column is nullable on purpose. Backfilling every existing row to 1 is
done here, but a row that somehow arrives with NULL is treated as
"uncounted" by ``services/row_revision.py`` and falls back to the v27
timestamp token instead of silently claiming an exactness it does not have.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_v30_row_revision_counter"
down_revision = "0012_v16_agent_collaboration_mesh"
branch_labels = None
depends_on = None

TABLES = ("companies", "departments", "members", "projects", "tasks")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("row_revision", sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table} SET row_revision = 1 WHERE row_revision IS NULL")


def downgrade():
    for table in TABLES:
        op.drop_column(table, "row_revision")
