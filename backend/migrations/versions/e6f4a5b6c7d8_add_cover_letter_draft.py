"""add_cover_letter_draft

Backfills the ``cover_letter_draft`` column on ``job_postings``. The column was
added to the ORM model with the AI draft_documents feature but never captured in
a migration, so any DB built from migrations was missing it (the jobs query
``SELECT ... cover_letter_draft ...`` failed with ``no such column``). Nullable —
it is populated only after the drafting node runs.

Revision ID: e6f4a5b6c7d8
Revises: d5e3f4a5b6c7
Create Date: 2026-06-16 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd5e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('cover_letter_draft', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'cover_letter_draft')
