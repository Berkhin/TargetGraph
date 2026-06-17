"""add_filtered_out_status

Adds the ``FILTERED_OUT`` value to the native Postgres ``job_status`` enum. Used
by the sourcing pre-screen to persist low-relevance postings without showing them
on the board or re-scraping them.

Dialect-aware: only Postgres has a native enum type to alter. On SQLite (the dev
/ test DB) the column is plain ``VARCHAR`` with no native type or CHECK
constraint, so the new value needs no schema change and this migration is a
no-op.

On Postgres, ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block,
so we commit the migration's implicit transaction first and use ``IF NOT EXISTS``
to keep the migration idempotent. Removing an enum value requires rebuilding the
whole type in Postgres, so ``downgrade`` is intentionally a no-op.

Revision ID: a8b6c7d8e9f0
Revises: f7a5b6c7d8e9
Create Date: 2026-06-17 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f7a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name != "postgresql":
        # SQLite (dev/test) stores the enum as plain VARCHAR with no native enum
        # type or CHECK constraint, so the new value needs no schema change.
        return
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; commit the
    # migration's implicit transaction before issuing it.
    op.execute("COMMIT")
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'FILTERED_OUT'")


def downgrade() -> None:
    """Downgrade schema.

    No-op: Postgres cannot drop a single enum value without recreating the type
    and rewriting every dependent column, which is not worth the risk here.
    """
    pass
