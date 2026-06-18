"""add_discarded_status

Adds the ``DISCARDED`` value to the native Postgres ``job_status`` enum. Set when
the user deletes a posting via the card's "delete" action: the card drops off
every board but the row is kept so the sourcing dedup (``source_job_id``) never
re-ingests it.

Dialect-aware: only Postgres has a native enum type to alter. On SQLite (the dev
/ test DB) the column is plain ``VARCHAR`` with no native type or CHECK
constraint, so the new value needs no schema change and this migration is a
no-op.

On Postgres, ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block,
so we commit the migration's implicit transaction first and use ``IF NOT EXISTS``
to keep the migration idempotent. Removing an enum value requires rebuilding the
whole type in Postgres, so ``downgrade`` is intentionally a no-op.

Revision ID: c0d9e8f7a6b5
Revises: b9c8d7e6f5a4
Create Date: 2026-06-18 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c0d9e8f7a6b5'
down_revision: Union[str, Sequence[str], None] = 'b9c8d7e6f5a4'
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
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'DISCARDED'")


def downgrade() -> None:
    """Downgrade schema.

    No-op: Postgres cannot drop a single enum value without recreating the type
    and rewriting every dependent column, which is not worth the risk here.
    """
    pass
