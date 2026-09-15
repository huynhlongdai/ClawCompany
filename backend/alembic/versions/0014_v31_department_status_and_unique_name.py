"""v31 department status column and a unique name per company

Revision ID: 0014_v31_department_status_and_unique_name
Revises: 0013_v30_row_revision_counter

Two debts, both named in section 21.6 of the handover.

1. Departments were the only node in the org tree without a status column.
   v29's cascade archive worked around that by flipping ``access_level`` to
   "confidential", which overloads a permission field to also mean "closed"
   and makes "who can read this" unanswerable.

2. Nothing stopped two departments in the same company from sharing a name,
   so "Engineering" could exist twice and every report that grouped by name
   quietly merged them.

The unique index is created *after* a duplicate check that raises instead of
mutating data. Auto-renaming duplicates during a migration would silently
rewrite rows an operator has never seen; refusing to upgrade forces a human
to decide which "Engineering" is the real one.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_v31_department_status_and_unique_name"
down_revision = "0013_v30_row_revision_counter"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_departments_company_name"

DUPLICATE_QUERY = """
SELECT company_id, name, COUNT(*) AS n
FROM departments
GROUP BY company_id, name
HAVING COUNT(*) > 1
"""


def upgrade():
    bind = op.get_bind()
    # v31 bugfix: check duplicates *before* any DDL. The first draft added
    # the column, backfilled it, and only then raised, which leaves the
    # schema half-migrated on any backend that does not roll DDL back with
    # the transaction (SQLite, MySQL). Refusing before touching anything
    # means a failed upgrade is a no-op an operator can safely re-run.
    duplicates = list(bind.execute(sa.text(DUPLICATE_QUERY)))
    if duplicates:
        listed = ", ".join(f"company {row[0]}: {row[1]!r} x{row[2]}" for row in duplicates)
        raise RuntimeError(
            "Cannot add a unique department name index while duplicates exist. "
            "Rename or archive one of each pair, then re-run this migration. "
            f"Duplicates: {listed}"
        )

    op.add_column("departments", sa.Column("status", sa.String(length=32), nullable=True))
    # Existing rows: v29 archived a department by setting access_level to
    # "confidential", so that is the only signal available about which ones
    # were closed. It is a guess, and it is the best guess available.
    op.execute("UPDATE departments SET status = 'active' WHERE status IS NULL")
    op.execute("UPDATE departments SET status = 'archived' "
               "WHERE access_level = 'confidential'")

    op.create_index(INDEX_NAME, "departments", ["company_id", "name"], unique=True)


def downgrade():
    op.drop_index(INDEX_NAME, table_name="departments")
    op.drop_column("departments", "status")
