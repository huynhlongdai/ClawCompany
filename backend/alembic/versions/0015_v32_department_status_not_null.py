"""v32: departments.status becomes NOT NULL with a server default of active.

The model has treated status as required since v31; the database did not.
v32 archives departments by setting status to archived, so a NULL status is
now ambiguous between never-set and not-archived.

Ordering matters and is the lesson from 0014: backfill first, verify, and
only then alter. SQLite cannot add a constraint in place, so batch mode
rebuilds the table and would abort halfway on a NULL. If any NULL survives
the backfill this raises before touching the schema, so a refusal is a no-op
and the migration stays re-runnable.

Revision ID: 0015_v32_department_status_not_null
Revises: 0014_v31_department_status_and_unique_name
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_v32_department_status_not_null"
down_revision = "0014_v31_department_status_and_unique_name"
branch_labels = None
depends_on = None

TABLE = "departments"
COLUMN = "status"
DEFAULT = "active"


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "UPDATE departments SET status = :value "
            "WHERE status IS NULL OR TRIM(status) = ''"
        ),
        {"value": DEFAULT},
    )

    remaining = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM departments "
            "WHERE status IS NULL OR TRIM(status) = ''"
        )
    ).scalar()

    if remaining:
        raise RuntimeError(
            f"{remaining} department rows still have an empty status; "
            "refusing to add NOT NULL. Set a status on those rows and re-run."
        )

    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=DEFAULT,
        )


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=32),
            nullable=True,
            server_default=None,
        )
